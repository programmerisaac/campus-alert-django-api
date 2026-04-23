# campusalert/alerts/services/delivery.py

"""
Alert delivery orchestration service — Phase 3.

Coordinates the full delivery pipeline for a dispatched alert:

    1. Fetches all active user FCM tokens from PostgreSQL
    2. Sends via FCM (internet channel — primary)
    3. Publishes to Redis pub/sub → picked up by WebSocket consumer (LAN channel)
    4. Records DeliveryLog entries for delivery tracking (F-12)
    5. Updates alert.status to 'dispatched'

The "offline" channel (PRD Method 3) is entirely Flutter-side:
    - Flutter detects no connectivity and caches the alert in SQLite
    - On reconnect, Flutter calls GET /api/v1/alerts/missed/?since=<timestamp>
    - The backend returns all alerts created after that timestamp
    - No server-side action needed for offline; the alert record always exists in PostgreSQL

Redis pub/sub for WebSocket broadcast:
    When this service publishes to the Redis channel "campusalert:alerts",
    the AlertWebSocketConsumer (alerts/consumers.py) is subscribed to that channel.
    Every connected WebSocket client (LAN devices) receives the alert payload
    within milliseconds — no polling, no Socket.IO server needed.
"""

import json
import logging
from typing import Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from alerts.models import Alert, DeliveryLog

logger = logging.getLogger('campusalert.delivery')

User = get_user_model()

# Redis pub/sub channel name — must match alerts/consumers.py REDIS_CHANNEL
REDIS_ALERT_CHANNEL = 'campusalert:alerts'


def dispatch_alert(alert_id: str) -> dict:
    """
    Full delivery pipeline for a single alert.

    Called by the Celery task (alerts/tasks.py) after the alert has been
    classified and saved. Runs asynchronously so it never blocks the admin's
    HTTP response.

    Args:
        alert_id: UUID string of the Alert to dispatch.

    Returns:
        Summary dict with delivery counts per channel.

    Raises:
        Alert.DoesNotExist: If the alert_id is invalid (task should not retry on this).
    """
    try:
        alert = Alert.objects.select_related('created_by').get(id=alert_id)
    except Alert.DoesNotExist:
        logger.error('dispatch_alert called with invalid alert_id: %s', alert_id)
        raise

    logger.info('Dispatching alert %s [%s] — "%s"', alert.id, alert.urgency, alert.title)

    # Fetch all active users with an FCM token for FCM delivery
    # Staff and students both receive all alerts in this version
    target_users = list(
        User.objects.filter(
            is_active=True,
            is_verified=True,
        )
        .exclude(id=alert.created_by_id)  # Admin who sent it doesn't need their own alert
        .values('id', 'fcm_token')
    )

    fcm_tokens = [u['fcm_token'] for u in target_users if u['fcm_token']]
    user_ids = [u['id'] for u in target_users]

    # ── Channel 1: FCM (internet delivery) ───────────────────────────────────
    fcm_results = _send_via_fcm(alert, fcm_tokens)

    # ── Channel 2: LAN WebSocket via Redis pub/sub ────────────────────────────
    # All users connected via WebSocket on the campus LAN will receive this
    lan_published = _publish_to_redis(alert)

    # ── Record delivery logs ──────────────────────────────────────────────────
    _record_delivery_logs(alert, user_ids, fcm_results)

    # ── Update alert status ───────────────────────────────────────────────────
    with transaction.atomic():
        Alert.objects.filter(id=alert.id).update(
            status=Alert.Status.DISPATCHED,
            dispatched_at=timezone.now(),
            recipient_count=len(user_ids),
        )

    summary = {
        'alert_id': str(alert.id),
        'urgency': alert.urgency,
        'recipients_targeted': len(user_ids),
        'fcm_attempted': len(fcm_tokens),
        'fcm_delivered': sum(1 for r in fcm_results if r.success),
        'lan_published': lan_published,
    }
    logger.info('Alert %s dispatched: %s', alert.id, summary)
    return summary


def _send_via_fcm(alert: Alert, fcm_tokens: list[str]) -> list:
    """
    Sends the alert to all users with FCM tokens.
    Handles the case where the FCM service is unavailable (logs warning, continues).

    Args:
        alert: The Alert instance to send.
        fcm_tokens: List of valid FCM device registration tokens.

    Returns:
        List of FCMResult objects from the FCM service.
    """
    if not fcm_tokens:
        logger.info('No FCM tokens to send for alert %s.', alert.id)
        return []

    try:
        from alerts.services.fcm import send_fcm_alert
        return send_fcm_alert(alert, fcm_tokens)
    except Exception as exc:
        # FCM failure must not prevent LAN delivery or alert status update
        logger.error(
            'FCM send failed for alert %s: %s. LAN delivery will still proceed.',
            alert.id,
            exc,
            exc_info=True,
        )
        return []


def _publish_to_redis(alert: Alert) -> bool:
    """
    Publishes the alert payload to the Redis pub/sub channel.

    All WebSocket consumers subscribed to REDIS_ALERT_CHANNEL will receive
    this message and forward it to their connected clients (LAN delivery).

    Args:
        alert: The Alert instance to broadcast.

    Returns:
        True if published successfully, False on error.
    """
    try:
        import redis as redis_lib
        from django.conf import settings

        r = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
        payload = json.dumps({
            'type': 'new_alert',
            'alert_id': str(alert.id),
            'title': alert.title,
            'body': alert.body,
            'urgency': alert.urgency,
            'category': alert.category,
            'created_at': alert.created_at.isoformat(),
            'created_by': alert.created_by.get_display_name(),
            'is_critical_or_high': alert.is_critical_or_high,
        })
        subscriber_count = r.publish(REDIS_ALERT_CHANNEL, payload)
        logger.info(
            'Published alert %s to Redis channel "%s" — %d subscriber(s) notified.',
            alert.id,
            REDIS_ALERT_CHANNEL,
            subscriber_count,
        )
        return True
    except Exception as exc:
        logger.error(
            'Redis publish failed for alert %s: %s. FCM delivery still proceeded.',
            alert.id,
            exc,
            exc_info=True,
        )
        return False


def _record_delivery_logs(alert: Alert, user_ids: list, fcm_results: list) -> None:
    """
    Creates DeliveryLog entries for all targeted users.

    FCM tokens successfully delivered → channel='fcm', delivered_at=now
    All other users → channel='fcm' with no delivered_at (pending/offline)

    In this version, LAN and offline delivery are tracked when the Flutter
    app calls the acknowledge endpoint, not at dispatch time.

    Args:
        alert: The Alert that was dispatched.
        user_ids: List of User PKs that were targeted.
        fcm_results: List of FCMResult objects from the FCM service.
    """
    if not user_ids:
        return

    successful_tokens = {r.token for r in fcm_results if r.success}
    now = timezone.now()

    # Build a token→user_id map for marking individual deliveries
    token_to_user = {
        u['fcm_token']: u['id']
        for u in User.objects.filter(id__in=user_ids).values('id', 'fcm_token')
        if u['fcm_token']
    }
    delivered_user_ids = {
        token_to_user[token]
        for token in successful_tokens
        if token in token_to_user
    }

    logs = []
    for user_id in user_ids:
        was_delivered_via_fcm = user_id in delivered_user_ids
        logs.append(DeliveryLog(
            alert=alert,
            user_id=user_id,
            channel=DeliveryLog.Channel.FCM,
            delivered_at=now if was_delivered_via_fcm else None,
        ))

    # Bulk insert — one query for all users, never a loop of .save()
    DeliveryLog.objects.bulk_create(logs, ignore_conflicts=True)
    logger.debug('Created %d DeliveryLog entries for alert %s.', len(logs), alert.id)


def get_missed_alerts(user, since_iso: Optional[str]) -> list[Alert]:
    """
    Returns all alerts created after the given ISO timestamp.

    Called by the Flutter offline sync endpoint:
        GET /api/v1/alerts/missed/?since=2024-01-01T12:00:00Z

    On reconnect, Flutter sends its last known alert timestamp.
    The backend returns every alert since then so SQLite cache can be updated.

    Args:
        user: The authenticated User requesting missed alerts.
        since_iso: ISO 8601 timestamp string of the last alert the user received.
                   If None or invalid, returns the last 50 alerts.

    Returns:
        Queryset of Alert objects ordered by created_at ascending (oldest first,
        so Flutter can process them in chronological order).
    """
    from django.utils.dateparse import parse_datetime

    base_qs = (
        Alert.objects
        .filter(status=Alert.Status.DISPATCHED)
        .select_related('created_by')
        .order_by('created_at')  # Ascending: oldest first for sequential sync
    )

    if since_iso:
        since_dt = parse_datetime(since_iso)
        if since_dt is not None:
            return base_qs.filter(created_at__gt=since_dt)
        else:
            logger.warning(
                'Could not parse since parameter "%s" for user %s. Returning last 50.',
                since_iso,
                user.id,
            )

    # Fallback: return the most recent 50 alerts if no valid timestamp provided
    return base_qs.order_by('-created_at')[:50]

