# campusalert/alerts/services/delivery.py

"""
Alert delivery orchestration service — Phase 3.

Coordinates the full delivery pipeline for a dispatched alert:

    1. Fetches all active, verified user FCM tokens from PostgreSQL
    2. Sends via FCM (internet channel — primary, F-07)
    3. Publishes to Redis pub/sub → AlertWebSocketConsumer broadcasts to LAN devices (F-08)
    4. Bulk-creates DeliveryLog entries for all targeted users (F-12)

The "offline" channel (F-09, PRD Method 3) is handled entirely by Flutter:
    - Flutter detects no connectivity and caches the alert payload in SQLite
    - On reconnect, Flutter calls GET /api/v1/alerts/missed/?since=<last_seen_at>
    - The backend returns alerts created after that timestamp (get_missed_alerts below)
    - No server-side action is needed for offline; every alert is always in PostgreSQL

Redis pub/sub replaces Socket.IO for LAN delivery.
When this service calls r.publish(REDIS_ALERT_CHANNEL, payload), every
AlertWebSocketConsumer that is subscribed and has a live WebSocket connection
receives the message and forwards it to the client device — instant, no polling.
"""

import json
import logging
from typing import Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('campusalert.delivery')

User = get_user_model()

# Redis pub/sub channel — must match REDIS_CHANNEL constant in alerts/consumers.py
REDIS_ALERT_CHANNEL = 'campusalert:alerts'


def dispatch_alert(alert_id: str) -> dict:
    """
    Full delivery pipeline for a single alert.

    Called by the Celery task (alerts/tasks.py) after the alert has been
    classified and saved to PostgreSQL. Runs asynchronously so it never
    blocks the admin's HTTP response.

    Args:
        alert_id: UUID string primary key of the Alert to dispatch.

    Returns:
        Summary dict with per-channel delivery counts.

    Raises:
        Alert.DoesNotExist: If alert_id is invalid. Celery will not retry
                            this — it is a programming error, not a transient failure.
    """
    from alerts.models import Alert

    try:
        alert = Alert.objects.select_related('created_by').get(id=alert_id, is_active=True)
    except Alert.DoesNotExist:
        logger.error('dispatch_alert called with invalid/inactive alert_id: %s', alert_id)
        raise

    logger.info('Dispatching alert %s [%s] — "%s"', alert.id, alert.urgency, alert.title)

    # Fetch all target users in one query.
    # Excludes the admin who created the alert — they don't need their own notification.
    target_users = list(
        User.objects.filter(is_active=True, is_verified=True)
        .exclude(id=alert.created_by_id)
        .values('id', 'fcm_token')
    )

    fcm_tokens = [u['fcm_token'] for u in target_users if u['fcm_token']]
    user_ids = [u['id'] for u in target_users]

    # ── Channel 1: FCM (internet delivery) ────────────────────────────────────
    fcm_results = _send_via_fcm(alert, fcm_tokens)

    # ── Channel 2: LAN WebSocket via Redis pub/sub ─────────────────────────────
    lan_published = _publish_to_redis(alert)

    # ── Record delivery logs in bulk ───────────────────────────────────────────
    _record_delivery_logs(alert, target_users, fcm_results)

    summary = {
        'alert_id': str(alert.id),
        'urgency': alert.urgency,
        'recipients_targeted': len(user_ids),
        'fcm_attempted': len(fcm_tokens),
        'fcm_delivered': sum(1 for r in fcm_results if r.success),
        'lan_published': lan_published,
    }
    logger.info('Alert %s dispatch complete: %s', alert.id, summary)
    return summary


def _send_via_fcm(alert, fcm_tokens: list[str]) -> list:
    """
    Sends the alert to all users with FCM tokens.
    FCM failure is non-fatal — LAN delivery continues regardless.

    Args:
        alert: Alert model instance.
        fcm_tokens: List of FCM device registration tokens.

    Returns:
        List of FCMResult objects (empty list on service failure).
    """
    if not fcm_tokens:
        logger.info('No FCM tokens to send for alert %s.', alert.id)
        return []

    try:
        from alerts.services.fcm import send_fcm_alert
        return send_fcm_alert(alert, fcm_tokens)
    except Exception as exc:
        # FCM unavailability must not prevent LAN delivery or log creation
        logger.error(
            'FCM send failed for alert %s: %s — LAN delivery will still proceed.',
            alert.id, exc, exc_info=True,
        )
        return []


def _publish_to_redis(alert) -> bool:
    """
    Publishes the alert payload to the Redis pub/sub channel.

    The AlertWebSocketConsumer subscribes to REDIS_ALERT_CHANNEL and
    broadcasts this message to all connected WebSocket clients (LAN devices).

    Args:
        alert: Alert model instance.

    Returns:
        True if the message was published, False on error.
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
            'is_high_priority': alert.is_high_priority,
        })
        subscriber_count = r.publish(REDIS_ALERT_CHANNEL, payload)
        logger.info(
            'Published alert %s to Redis channel "%s" — %d WebSocket subscriber(s) notified.',
            alert.id, REDIS_ALERT_CHANNEL, subscriber_count,
        )
        return True
    except Exception as exc:
        logger.error(
            'Redis publish failed for alert %s: %s', alert.id, exc, exc_info=True,
        )
        return False


def _record_delivery_logs(alert, target_users: list[dict], fcm_results: list) -> None:
    """
    Bulk-creates DeliveryLog entries for all targeted users.

    Uses bulk_create with ignore_conflicts=True to handle edge cases where
    a log entry already exists (e.g. Celery task retry after partial completion).
    Never loops with .save() — one DB round-trip for all users.

    Args:
        alert: The Alert that was dispatched.
        target_users: List of {'id': uuid, 'fcm_token': str|None} dicts.
        fcm_results: List of FCMResult objects from the FCM service.
    """
    from alerts.models import DeliveryLog

    if not target_users:
        return

    # Build a set of tokens that were successfully delivered via FCM
    successful_tokens = {r.token for r in fcm_results if r.success}
    # Build a map from token → user_id for identifying successful recipients
    token_to_user_id = {
        u['fcm_token']: u['id']
        for u in target_users
        if u['fcm_token']
    }
    delivered_user_ids = {
        token_to_user_id[token]
        for token in successful_tokens
        if token in token_to_user_id
    }

    now = timezone.now()
    logs = []
    for user in target_users:
        was_fcm_delivered = user['id'] in delivered_user_ids
        logs.append(DeliveryLog(
            alert=alert,
            user_id=user['id'],
            channel=DeliveryLog.Channel.FCM,
            delivered_at=now if was_fcm_delivered else None,
        ))

    DeliveryLog.objects.bulk_create(logs, ignore_conflicts=True)
    logger.debug('Created %d DeliveryLog entries for alert %s.', len(logs), alert.id)


def get_missed_alerts(user, since_iso: Optional[str]):
    """
    Returns alerts created after a given ISO 8601 timestamp.

    Called by the Flutter offline sync flow:
        GET /api/v1/alerts/missed/?since=2024-01-01T12:00:00Z

    On reconnect, Flutter sends its last known alert timestamp. The backend
    returns every active alert since then — Flutter updates its SQLite cache
    and displays any alerts the user missed while offline.

    Args:
        user: Authenticated User instance (reserved for future per-role filtering).
        since_iso: ISO 8601 string of the last alert the user received.
                   If None or unparseable, returns the 50 most recent alerts.

    Returns:
        Queryset of Alert objects ordered ascending (oldest first) so Flutter
        can process them in chronological order.
    """
    from alerts.models import Alert
    from django.utils.dateparse import parse_datetime

    base_qs = (
        Alert.objects
        .filter(is_active=True)
        .select_related('created_by')
        .order_by('created_at')  # Oldest first for sequential sync
    )

    if since_iso:
        since_dt = parse_datetime(since_iso)
        if since_dt is not None:
            return base_qs.filter(created_at__gt=since_dt)
        else:
            logger.warning(
                'Unparseable since parameter "%s" for user %s. Returning last 50.',
                since_iso, user.id,
            )

    # Fallback: return 50 most recent alerts if no valid timestamp
    return Alert.objects.filter(is_active=True).select_related('created_by').order_by('-created_at')[:50]
