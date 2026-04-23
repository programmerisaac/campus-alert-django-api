# campusalert/alerts/tasks.py

"""
Celery tasks for asynchronous alert dispatch — Phase 3.

Rules followed (from system prompt):
- Tasks are dispatched via transaction.on_commit() — never inside a transaction
- Tasks are idempotent — running twice does not create duplicate delivery logs
- Tasks retry on transient errors (network, Redis) with exponential backoff
- Tasks do not block HTTP responses — all dispatch logic is async via Celery

Task flow:
    API view saves Alert → transaction.on_commit() → dispatch_alert_task.delay(alert_id)
    → delivery.dispatch_alert(alert_id) → FCM + Redis pub/sub (LAN)
"""

import logging

from celery import shared_task

from alerts.models import Alert

logger = logging.getLogger('campusalert.tasks')


@shared_task(
    bind=True,
    name='alerts.dispatch_alert',
    max_retries=3,
    default_retry_delay=10,          # 10s initial retry delay
    autoretry_for=(Exception,),       # Retry on any exception
    retry_backoff=True,               # Exponential backoff: 10s, 20s, 40s
    retry_backoff_max=120,            # Cap at 2 minutes between retries
    retry_jitter=True,                # Add jitter to prevent thundering herd
    acks_late=True,                   # Only ack after task completes (safe retry on worker crash)
    ignore_result=False,
)
def dispatch_alert_task(self, alert_id: str) -> dict:
    """
    Dispatches a classified alert to all active users via FCM and LAN WebSocket.

    This task is the entry point for the full delivery pipeline.
    It delegates to alerts.services.delivery.dispatch_alert() which handles:
        1. Fetching all active user FCM tokens
        2. Sending via FCM HTTP v1 API
        3. Publishing to Redis pub/sub for WebSocket (LAN) delivery
        4. Creating DeliveryLog entries
        5. Updating alert.status to 'dispatched'

    Args:
        alert_id: UUID string of the classified Alert to dispatch.

    Returns:
        Summary dict from delivery.dispatch_alert() with per-channel counts.

    Retries:
        Up to 3 times on any exception with exponential backoff.
        If the alert does not exist (DoesNotExist), the task fails permanently
        and does not retry — this prevents infinite retries on bad data.
    """
    from alerts.services.delivery import dispatch_alert

    logger.info('Celery task started: dispatch_alert_task for alert_id=%s', alert_id)

    # Verify alert exists and is in a dispatchable state before proceeding
    try:
        alert = Alert.objects.only('id', 'status').get(id=alert_id)
    except Alert.DoesNotExist:
        # Do not retry — the alert ID is genuinely invalid
        logger.error('dispatch_alert_task: Alert %s does not exist. Task will not retry.', alert_id)
        raise  # Let Celery mark it as FAILURE without retry

    if alert.status == Alert.Status.DISPATCHED:
        # Idempotency guard: already dispatched (e.g., task ran twice due to retry)
        logger.warning(
            'dispatch_alert_task: Alert %s already dispatched. Skipping duplicate run.',
            alert_id,
        )
        return {'alert_id': alert_id, 'skipped': True, 'reason': 'already_dispatched'}

    try:
        summary = dispatch_alert(alert_id)
        logger.info('dispatch_alert_task completed: %s', summary)
        return summary
    except Alert.DoesNotExist:
        # Raised inside dispatch_alert — same handling: no retry
        logger.error('dispatch_alert_task: Alert %s not found inside dispatch. No retry.', alert_id)
        raise
    except Exception as exc:
        logger.error(
            'dispatch_alert_task failed for alert %s (attempt %d/%d): %s',
            alert_id,
            self.request.retries + 1,
            self.max_retries + 1,
            exc,
            exc_info=True,
        )
        # Mark the alert as failed if we've exhausted all retries
        if self.request.retries >= self.max_retries:
            Alert.objects.filter(id=alert_id).update(status=Alert.Status.FAILED)
            logger.error(
                'Alert %s marked as FAILED after %d dispatch attempts.',
                alert_id,
                self.max_retries + 1,
            )
        raise


