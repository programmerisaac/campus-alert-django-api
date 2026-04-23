# campusalert/website/asgi.py

"""
ASGI configuration for CampusAlert.

Django 6.x provides native WebSocket support through ASGI.
No django-channels is needed. We route HTTP requests to Django's
ASGI app and WebSocket connections to our native consumers.

LAN delivery works by having all student devices connect to:
    ws://<server_lan_ip>:8000/ws/alerts/?token=<jwt>

The Celery dispatch task publishes to Redis, and this consumer
forwards alerts to all connected WebSocket clients in real time.
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'website.settings')

# Must initialise Django before importing consumers or models
from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

# Consumers are imported after Django initialisation
from alerts.consumers import AlertWebSocketConsumer  # noqa: E402


async def _websocket_router(scope: dict, receive, send) -> None:
    """
    Routes incoming WebSocket connections to the correct consumer.
    Unknown paths are rejected with code 4004 (Not Found).
    """
    path = scope.get('path', '')

    route_map: dict[str, type] = {
        '/ws/alerts/': AlertWebSocketConsumer,
    }

    consumer_class = route_map.get(path)
    if consumer_class is not None:
        consumer = consumer_class(scope)
        await consumer(receive, send)
    else:
        # Reject unknown WebSocket paths cleanly
        await send({'type': 'websocket.close', 'code': 4004})


async def application(scope: dict, receive, send) -> None:
    """
    Top-level ASGI application.
    Dispatches to Django (HTTP) or our WebSocket router based on protocol.
    """
    protocol = scope.get('type', '')

    if protocol == 'http':
        await django_asgi_app(scope, receive, send)
    elif protocol == 'websocket':
        await _websocket_router(scope, receive, send)
    else:
        raise NotImplementedError(f"CampusAlert ASGI does not support protocol: {protocol!r}")

