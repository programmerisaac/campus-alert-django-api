# campusalert/alerts/consumers.py

"""
Native ASGI WebSocket consumer for LAN alert delivery — Phase 3.

This replaces Socket.IO (PRD §5, Method 2, F-08) entirely.

How LAN delivery works:
    1. Flutter connects to ws://<server_lan_ip>:8000/ws/alerts/?token=<jwt>
       on every app launch (while on campus Wi-Fi).
    2. This consumer authenticates the JWT, then subscribes to the Redis
       pub/sub channel 'campusalert:alerts' in a background asyncio task.
    3. When the delivery service publishes a new alert to Redis (after FCM dispatch),
       this consumer forwards the JSON payload to all connected WebSocket clients.
    4. Flutter receives the payload and shows the notification / full-screen overlay
       via the same code path as FCM delivery.

Authentication:
    JWT token passed as query parameter: ?token=<access_token>
    This is necessary because WebSocket handshakes cannot carry Authorization headers
    in the standard browser WebSocket API. Flutter's web_socket_channel package
    follows the same constraint.

Why no django-channels:
    Django 6.x ASGI supports WebSockets natively. This consumer is a plain
    async Python class following the ASGI WebSocket spec. It is wired up in
    website/asgi.py. No channel layers, no channel names, no Channels package needed.
"""

import asyncio
import json
import logging
from typing import Optional
from urllib.parse import parse_qs

logger = logging.getLogger('campusalert.websocket')

# Redis pub/sub channel — must match alerts/services/delivery.py REDIS_ALERT_CHANNEL
REDIS_CHANNEL = 'campusalert:alerts'

# How often to send a heartbeat ping to keep the connection alive through NAT
HEARTBEAT_INTERVAL_SECONDS = 30

# Max wait for a message before rechecking the connection state
REDIS_POLL_TIMEOUT_SECONDS = 1.0


class AlertWebSocketConsumer:
    """
    WebSocket consumer for real-time alert delivery over the campus LAN.

    Each connected Flutter client gets one instance of this class.
    The consumer:
        - Authenticates via JWT query parameter
        - Subscribes to the Redis pub/sub channel
        - Forwards incoming Redis messages to the connected client
        - Sends periodic heartbeats to maintain the connection
        - Cleans up Redis and asyncio tasks on disconnect
    """

    def __init__(self, scope: dict) -> None:
        self.scope = scope
        self._send = None
        self._receive = None
        self.user = None
        self.is_connected = False
        self._tasks: list[asyncio.Task] = []

    async def __call__(self, receive, send) -> None:
        """
        ASGI callable entry point.
        Called by the ASGI router in website/asgi.py for each new WebSocket connection.
        """
        self._receive = receive
        self._send = send

        # ── Step 1: Extract and validate JWT from query string ─────────────────
        token_str = self._extract_token()
        if not token_str:
            logger.warning('WebSocket connection rejected — no token in query string.')
            await self._close(code=4001, reason='Authentication token required.')
            return

        self.user = await self._authenticate_jwt(token_str)
        if self.user is None:
            logger.warning('WebSocket connection rejected — invalid or expired JWT.')
            await self._close(code=4003, reason='Invalid or expired token.')
            return

        # ── Step 2: Accept the connection ─────────────────────────────────────
        await self._accept()
        self.is_connected = True
        logger.info(
            'WebSocket connected: user=%s [%s]',
            self.user.get('username', 'unknown'),
            self.scope.get('client', ['?'])[0],
        )

        # Send a welcome message so Flutter knows the connection is live
        await self._send_json({
            'type': 'connected',
            'message': 'CampusAlert LAN channel active.',
            'user_id': self.user.get('user_id'),
        })

        # ── Step 3: Start background tasks ────────────────────────────────────
        # Redis listener and heartbeat run concurrently with the receive loop
        redis_task = asyncio.create_task(self._redis_listener())
        heartbeat_task = asyncio.create_task(self._heartbeat())
        self._tasks = [redis_task, heartbeat_task]

        try:
            # ── Step 4: Main receive loop ──────────────────────────────────────
            await self._receive_loop()
        finally:
            self.is_connected = False
            for task in self._tasks:
                task.cancel()
            logger.info(
                'WebSocket disconnected: user=%s',
                self.user.get('username', 'unknown') if self.user else 'unknown',
            )

    # ── Authentication ────────────────────────────────────────────────────────

    def _extract_token(self) -> Optional[str]:
        """
        Extracts the JWT access token from the WebSocket query string.
        Expected format: ws://server/ws/alerts/?token=<access_token>
        """
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        params = parse_qs(query_string)
        token_list = params.get('token', [])
        return token_list[0] if token_list else None

    async def _authenticate_jwt(self, token_str: str) -> Optional[dict]:
        """
        Validates the JWT access token and returns the decoded payload.

        Runs the synchronous JWT validation in a thread pool via asyncio.to_thread
        so it does not block the event loop.

        Args:
            token_str: Raw JWT access token string.

        Returns:
            Decoded token payload dict, or None if validation fails.
        """
        try:
            return await asyncio.to_thread(self._validate_token_sync, token_str)
        except Exception as exc:
            logger.warning('JWT validation error in WebSocket consumer: %s', exc)
            return None

    @staticmethod
    def _validate_token_sync(token_str: str) -> Optional[dict]:
        """
        Synchronous JWT validation using simplejwt's UntypedToken.
        Raises TokenError if the token is expired, invalid, or tampered with.

        Returns a dict with at minimum: user_id, username, role.
        """
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import UntypedToken
        from django.contrib.auth import get_user_model

        User = get_user_model()

        try:
            validated = UntypedToken(token_str)
            user_id = validated.get('user_id')
            if not user_id:
                return None

            # Fetch minimal user data needed for logging and auth checks
            user = User.objects.values('id', 'username', 'role', 'is_active', 'is_verified').get(
                id=user_id,
                is_active=True,
            )
            return {
                'user_id': str(user['id']),
                'username': user['username'],
                'role': user['role'],
                'is_verified': user['is_verified'],
            }
        except (TokenError, User.DoesNotExist):
            return None

    # ── ASGI WebSocket protocol ───────────────────────────────────────────────

    async def _accept(self) -> None:
        """Sends the WebSocket accept handshake response."""
        await self._send({'type': 'websocket.accept'})

    async def _close(self, code: int = 1000, reason: str = '') -> None:
        """Rejects or closes the WebSocket connection with a code and reason."""
        try:
            await self._send({'type': 'websocket.close', 'code': code})
        except Exception:
            pass  # Already closed

    async def _send_json(self, data: dict) -> None:
        """
        Sends a JSON-serialized payload to the connected Flutter client.
        No-op if the connection is already closed.
        """
        if not self.is_connected:
            return
        try:
            await self._send({
                'type': 'websocket.send',
                'text': json.dumps(data, default=str),
            })
        except Exception as exc:
            logger.debug('WebSocket send failed (client likely disconnected): %s', exc)
            self.is_connected = False

    async def _receive_loop(self) -> None:
        """
        Listens for incoming messages and disconnect events from the Flutter client.
        In this version, clients only send pong responses to heartbeat pings.
        The loop exits when the client disconnects.
        """
        while True:
            try:
                message = await self._receive()
            except Exception:
                break

            msg_type = message.get('type', '')

            if msg_type == 'websocket.disconnect':
                break
            elif msg_type == 'websocket.receive':
                text = message.get('text', '')
                if text:
                    try:
                        data = json.loads(text)
                        if data.get('type') == 'pong':
                            # Client acknowledged our heartbeat ping — connection is alive
                            pass
                    except json.JSONDecodeError:
                        pass  # Ignore malformed messages from client

    # ── Redis subscriber ──────────────────────────────────────────────────────

    async def _redis_listener(self) -> None:
        """
        Subscribes to the Redis pub/sub channel and forwards alert messages
        to the connected Flutter client.

        Runs as a background asyncio task. Exits cleanly when:
        - The WebSocket connection is closed (is_connected becomes False)
        - The task is cancelled (by the cleanup in __call__)
        - A non-recoverable Redis error occurs

        The polling loop uses a timeout on get_message() so it checks
        is_connected regularly rather than blocking indefinitely.
        """
        try:
            import redis.asyncio as aioredis
            from django.conf import settings

            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(REDIS_CHANNEL)
            logger.debug(
                'WebSocket consumer subscribed to Redis channel "%s" for user %s.',
                REDIS_CHANNEL,
                self.user.get('username'),
            )

            while self.is_connected:
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=REDIS_POLL_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    # Normal — just loop and check is_connected again
                    continue

                if message is None:
                    continue

                if message['type'] == 'message':
                    data_str = message.get('data', '')
                    try:
                        payload = json.loads(data_str)
                        await self._send_json(payload)
                        logger.debug(
                            'Forwarded Redis alert to WebSocket user %s: type=%s',
                            self.user.get('username'),
                            payload.get('type'),
                        )
                    except json.JSONDecodeError:
                        logger.warning('Received non-JSON message from Redis: %s', data_str[:100])

        except asyncio.CancelledError:
            logger.debug('Redis listener task cancelled for user %s.', self.user.get('username'))
        except Exception as exc:
            logger.error(
                'Redis listener error for user %s: %s',
                self.user.get('username', 'unknown'),
                exc,
                exc_info=True,
            )
        finally:
            try:
                await pubsub.unsubscribe(REDIS_CHANNEL)
                await r.aclose()
            except Exception:
                pass

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def _heartbeat(self) -> None:
        """
        Sends a ping every HEARTBEAT_INTERVAL_SECONDS to keep the connection
        alive through NAT/firewall idle timeouts on campus Wi-Fi routers.

        Flutter responds with { "type": "pong" } which the receive loop handles.
        """
        try:
            while self.is_connected:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                if self.is_connected:
                    await self._send_json({'type': 'ping'})
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug('Heartbeat task ended for user %s: %s', self.user.get('username'), exc)



