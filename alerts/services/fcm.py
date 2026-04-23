# campusalert/alerts/services/fcm.py

"""
Firebase Cloud Messaging (FCM) HTTP v1 API service — Phase 3.

Sends push notifications to Android devices via FCM.
Internet delivery is the primary channel (PRD §5, Method 1, F-07).

FCM HTTP v1 API differences from legacy FCM:
    - Uses OAuth 2.0 Bearer token (not the deprecated server key)
    - Token is short-lived (1 hour) and refreshed automatically via firebase-admin SDK
    - Supports batch sends up to 500 tokens per request
    - Returns per-message success/failure details for delivery tracking

Full-screen behaviour for Critical/High:
    Flutter interprets the `urgency` field in the data payload and
    shows the full-screen overlay. The FCM notification payload sets
    `priority: high` and `android.notification.visibility: PUBLIC`
    so the notification appears even on locked screens.

Usage (called from alerts/tasks.py):
    from alerts.services.fcm import send_fcm_alert
    results = send_fcm_alert(alert, fcm_tokens)
"""

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger('campusalert.fcm')

# FCM HTTP v1 endpoint — project-specific
FCM_SEND_URL = 'https://fcm.googleapis.com/v1/projects/{project_id}/messages:send'
FCM_BATCH_URL = 'https://fcm.googleapis.com/batch'

# Urgency → FCM Android notification priority mapping
FCM_PRIORITY_MAP = {
    'critical': 'high',
    'high': 'high',
    'medium': 'normal',
    'low': 'normal',
}

# Urgency → FCM notification channel ID (must match Flutter AndroidNotificationChannel IDs)
FCM_CHANNEL_MAP = {
    'critical': 'campusalert_critical',
    'high': 'campusalert_high',
    'medium': 'campusalert_medium',
    'low': 'campusalert_low',
}


@dataclass
class FCMResult:
    """Result of a single FCM send attempt."""
    token: str
    success: bool
    message_id: Optional[str] = None
    error_code: Optional[str] = None


def _get_access_token() -> str:
    """
    Retrieves a valid OAuth 2.0 Bearer token from the Firebase Admin SDK.
    The SDK handles token caching and refresh automatically.

    Returns:
        A valid Bearer token string.

    Raises:
        RuntimeError: If Firebase credentials are not configured.
    """
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging  # noqa: F401 — ensures SDK loaded
    except ImportError as exc:
        raise ImportError('firebase-admin is required. Run: pip install firebase-admin') from exc

    from django.conf import settings

    # Initialise Firebase app once — subsequent calls reuse the existing app
    if not firebase_admin._apps:
        service_account_path = settings.FCM_SERVICE_ACCOUNT_JSON_PATH
        if not service_account_path:
            raise RuntimeError(
                'FCM_SERVICE_ACCOUNT_JSON_PATH is not configured in settings. '
                'Download the service account JSON from the Firebase Console.'
            )
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred)

    # Use the Admin SDK's internal credential to get an access token
    app = firebase_admin.get_app()
    token = app.credential.get_access_token().access_token
    return token


def _build_fcm_message(token: str, alert) -> dict:
    """
    Constructs the FCM HTTP v1 message payload for a single device token.

    The `data` payload is what the Flutter app reads to:
        - Show the full-screen overlay (urgency=critical or high)
        - Store the alert in SQLite
        - Update the alert feed

    The `notification` payload is what FCM uses to show the system notification
    when the app is in the background or closed.

    Args:
        token: FCM registration token for the target device.
        alert: An Alert model instance.

    Returns:
        A dict representing the FCM HTTP v1 message body.
    """
    urgency = alert.urgency
    fcm_priority = FCM_PRIORITY_MAP.get(urgency, 'normal')
    channel_id = FCM_CHANNEL_MAP.get(urgency, 'campusalert_low')

    return {
        'message': {
            'token': token,
            # Data payload — always delivered, readable even when app is closed
            'data': {
                'alert_id': str(alert.id),
                'title': alert.title,
                'body': alert.body,
                'urgency': urgency,
                'category': alert.category,
                'created_at': alert.created_at.isoformat(),
                'channel_id': channel_id,
                # Flutter checks this flag to trigger full-screen overlay
                'is_critical_or_high': str(alert.is_critical_or_high).lower(),
            },
            # Notification payload — displayed by FCM when app is in background
            'notification': {
                'title': alert.title,
                'body': alert.body[:200],  # Truncate for notification display
            },
            # Android-specific configuration
            'android': {
                'priority': fcm_priority,
                'notification': {
                    'channel_id': channel_id,
                    'notification_priority': (
                        'PRIORITY_MAX' if urgency in ('critical', 'high')
                        else 'PRIORITY_DEFAULT'
                    ),
                    'visibility': 'PUBLIC',
                    # Sound and vibration for Critical/High
                    'default_sound': urgency in ('critical', 'high'),
                    'default_vibrate_timings': urgency in ('critical', 'high'),
                },
            },
        }
    }


def send_fcm_alert(alert, fcm_tokens: list[str]) -> list[FCMResult]:
    """
    Sends an alert to a list of FCM device tokens using the HTTP v1 API.

    FCM HTTP v1 does not support true batch sends in a single API call
    (unlike the legacy API). We iterate through tokens and send individually.
    For large deployments (5,000+ users), this is called from a Celery task
    with chunked token batches to stay within rate limits.

    PRD target: < 2 seconds end-to-end for internet delivery.
    This function is called inside a Celery task so it does not block the
    HTTP response to the admin.

    Args:
        alert: An Alert model instance (must have id, title, body, urgency, category).
        fcm_tokens: List of FCM registration tokens for target devices.

    Returns:
        List of FCMResult objects, one per token, indicating success or failure.
    """
    from django.conf import settings

    if not fcm_tokens:
        logger.info('No FCM tokens provided for alert %s — skipping FCM send.', alert.id)
        return []

    project_id = settings.FCM_PROJECT_ID
    if not project_id:
        logger.error('FCM_PROJECT_ID is not configured. Cannot send FCM alerts.')
        return [
            FCMResult(token=t, success=False, error_code='MISCONFIGURED')
            for t in fcm_tokens
        ]

    try:
        access_token = _get_access_token()
    except (RuntimeError, ImportError) as exc:
        logger.error('FCM access token retrieval failed: %s', exc)
        return [
            FCMResult(token=t, success=False, error_code='AUTH_FAILED')
            for t in fcm_tokens
        ]

    send_url = FCM_SEND_URL.format(project_id=project_id)
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    results: list[FCMResult] = []

    for token in fcm_tokens:
        payload = _build_fcm_message(token, alert)
        try:
            response = requests.post(
                send_url,
                json=payload,
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                message_id = data.get('name', '')
                results.append(FCMResult(token=token, success=True, message_id=message_id))
                logger.debug('FCM sent to token ...%s — message_id: %s', token[-8:], message_id)
            else:
                error_data = response.json()
                error_code = (
                    error_data.get('error', {}).get('status', 'UNKNOWN_ERROR')
                )
                results.append(FCMResult(token=token, success=False, error_code=error_code))
                logger.warning(
                    'FCM delivery failed for token ...%s — status: %s error: %s',
                    token[-8:],
                    response.status_code,
                    error_code,
                )

        except requests.Timeout:
            results.append(FCMResult(token=token, success=False, error_code='TIMEOUT'))
            logger.warning('FCM request timed out for token ...%s', token[-8:])
        except requests.RequestException as exc:
            results.append(FCMResult(token=token, success=False, error_code='NETWORK_ERROR'))
            logger.error('FCM network error for token ...%s: %s', token[-8:], exc)

    success_count = sum(1 for r in results if r.success)
    logger.info(
        'FCM dispatch complete for alert %s — %d/%d delivered.',
        alert.id,
        success_count,
        len(fcm_tokens),
    )

    return results

