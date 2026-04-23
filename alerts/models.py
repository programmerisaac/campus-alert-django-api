# campusalert/alerts/models.py

"""
Alert and DeliveryLog models for CampusAlert.

Alert       — every message composed by an administrator, with urgency classification
              metadata, status tracking, and dispatch counters.
DeliveryLog — per-user per-alert delivery record (channel, delivery time, acknowledgement).
"""

import logging

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel

logger = logging.getLogger('campusalert.alerts')


class Alert(TimeStampedModel):
    """
    Represents a single alert message composed and dispatched by an administrator.

    Lifecycle:
        DRAFT → CLASSIFIED → DISPATCHED (set by Celery task after delivery)

    Classification pipeline (PRD §3.2):
        1. Keyword override — instant, no ML inference
        2. XGBoost + TF-IDF — < 500ms, probabilistic classification

    Key fields:
        urgency               — Critical / High / Medium / Low
        classification_method — keyword_override or xgboost
        classification_confidence — XGBoost probability score (None for keyword override)
        status                — draft | classified | dispatched
        dispatched_at         — when Celery finished dispatching
        recipient_count       — number of users targeted
        is_active             — False = admin retracted the alert (soft delete)
    """

    class Urgency(models.TextChoices):
        CRITICAL = 'critical', _('Critical')
        HIGH = 'high', _('High')
        MEDIUM = 'medium', _('Medium')
        LOW = 'low', _('Low')

    class Category(models.TextChoices):
        SECURITY = 'security', _('Security')
        HEALTH = 'health', _('Health')
        ACADEMIC = 'academic', _('Academic')
        GENERAL = 'general', _('General')

    class ClassificationMethod(models.TextChoices):
        KEYWORD = 'keyword_override', _('Keyword Override')
        XGBOOST = 'xgboost', _('XGBoost')

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        CLASSIFIED = 'classified', _('Classified')
        DISPATCHED = 'dispatched', _('Dispatched')
        FAILED = 'failed', _('Failed')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='alerts_created',
        db_index=True,
        help_text='The administrator account that composed and submitted this alert.',
    )

    title = models.CharField(
        max_length=200,
        help_text='Short title shown in the notification header.',
    )

    body = models.TextField(
        help_text='Full alert message body displayed when the user opens the alert.',
    )

    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.GENERAL,
        db_index=True,
    )

    urgency = models.CharField(
        max_length=10,
        choices=Urgency.choices,
        db_index=True,
        help_text='Urgency level assigned by the classification pipeline.',
    )

    classification_method = models.CharField(
        max_length=20,
        choices=ClassificationMethod.choices,
        help_text='Whether urgency was assigned via keyword override or XGBoost.',
    )

    # XGBoost probability score for the predicted class (0.0–1.0).
    # None when urgency was assigned via keyword override (no model inference run).
    classification_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text='XGBoost prediction confidence (0–1). None for keyword override.',
    )

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.CLASSIFIED,
        db_index=True,
        help_text='Lifecycle status. Set to DISPATCHED by the Celery delivery task.',
    )

    # Set by the Celery delivery task once FCM + LAN dispatch is complete
    dispatched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the Celery task finished dispatching this alert.',
    )

    # Number of users targeted for delivery — set after fetching the user list
    recipient_count = models.PositiveIntegerField(
        default=0,
        help_text='Total number of users this alert was sent to.',
    )

    # Soft delete — allows retraction without destroying delivery logs
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text='False if the alert has been retracted by an administrator.',
    )

    class Meta:
        verbose_name = 'Alert'
        verbose_name_plural = 'Alerts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['urgency', 'is_active'], name='alert_urgency_active_idx'),
            models.Index(fields=['status', 'created_at'], name='alert_status_time_idx'),
            models.Index(fields=['created_by', 'created_at'], name='alert_creator_time_idx'),
            models.Index(fields=['category', 'urgency'], name='alert_cat_urgency_idx'),
        ]

    def __str__(self) -> str:
        return f'[{self.urgency.upper()}] {self.title}'

    @property
    def is_high_priority(self) -> bool:
        """True for alerts that trigger full-screen takeover on the device (PRD §3.1)."""
        return self.urgency in (self.Urgency.CRITICAL, self.Urgency.HIGH)

    # Alias used in serializers and delivery service
    @property
    def is_critical_or_high(self) -> bool:
        return self.is_high_priority


class DeliveryLog(TimeStampedModel):
    """
    Records the delivery status of a single alert to a single user (F-12).

    One row per (alert, user) pair per channel. The channel records which delivery
    path reached the device: FCM (internet), LAN WebSocket, or offline stored.

    acknowledged_at is set when the user taps "Acknowledge" on the full-screen
    overlay for Critical/High alerts — recorded via POST /api/v1/alerts/<id>/acknowledge/
    """

    class Channel(models.TextChoices):
        FCM = 'fcm', _('Firebase Cloud Messaging')
        LAN = 'lan_websocket', _('LAN WebSocket')
        OFFLINE = 'offline_stored', _('Offline (stored on device)')

    alert = models.ForeignKey(
        Alert,
        on_delete=models.CASCADE,
        related_name='delivery_logs',
        db_index=True,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='alert_deliveries',
        db_index=True,
    )

    channel = models.CharField(
        max_length=20,
        choices=Channel.choices,
        db_index=True,
    )

    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the backend confirmed delivery via this channel.',
    )

    acknowledged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the user tapped Acknowledge on a Critical/High full-screen alert.',
    )

    fcm_message_id = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Firebase message ID for FCM deliveries (for debugging).',
    )

    class Meta:
        verbose_name = 'Delivery Log'
        verbose_name_plural = 'Delivery Logs'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['alert', 'user'],
                name='unique_delivery_per_alert_user',
            )
        ]
        indexes = [
            models.Index(fields=['user', 'delivered_at'], name='delivery_user_time_idx'),
            models.Index(fields=['alert', 'channel'], name='delivery_alert_channel_idx'),
        ]

    def __str__(self) -> str:
        return f'Alert {self.alert_id} → {self.user_id} via {self.channel}'


