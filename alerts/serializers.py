# campusalert/alerts/serializers.py

"""
Serializers for the alerts app.

AlertCreateSerializer        — Admin input: title, body, category (urgency assigned by pipeline)
AlertListSerializer          — Compact alert representation for feed and missed-alerts list
AlertDetailSerializer        — Full alert detail including classification metadata
AlertAcknowledgeSerializer   — Student input: channel used to receive the alert
AlertDeliveryStatusSerializer — Admin view: alert + full delivery log with per-user status
"""

import logging

from django.utils import timezone
from rest_framework import serializers

from accounts.serializers import UserProfileSerializer

from .models import Alert, DeliveryLog

logger = logging.getLogger('campusalert.alerts.serializers')


# ─────────────────────────────────────────────────────────────────────────────
# Admin Input
# ─────────────────────────────────────────────────────────────────────────────

class AlertCreateSerializer(serializers.Serializer):
    """
    Validates the payload submitted by an admin when composing a new alert.

    Urgency is intentionally excluded — it is assigned by the classification
    pipeline (keyword override or XGBoost) after this serializer validates.
    The admin supplies title, body, and an optional category.
    """

    title = serializers.CharField(
        max_length=200,
        help_text='Short title shown in the notification header.',
    )
    body = serializers.CharField(
        help_text='Full alert message body.',
    )
    category = serializers.ChoiceField(
        choices=Alert.Category.choices,
        default=Alert.Category.GENERAL,
        required=False,
        help_text='Alert category (security, health, academic, general).',
    )

    def validate_title(self, value: str) -> str:
        """Strip whitespace and reject blank titles."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Title must not be blank.')
        return value

    def validate_body(self, value: str) -> str:
        """Strip whitespace and enforce a minimum content length."""
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError(
                'Alert body must be at least 10 characters.'
            )
        return value


# ─────────────────────────────────────────────────────────────────────────────
# Student / Staff Read Serializers
# ─────────────────────────────────────────────────────────────────────────────

class AlertListSerializer(serializers.ModelSerializer):
    """
    Compact alert representation used in:
    - GET /api/v1/alerts/          (AlertFeedView)
    - GET /api/v1/alerts/missed/   (MissedAlertsView)

    Omits classification metadata (method, confidence) to keep the payload
    small for list rendering and offline sync. Full details are fetched
    individually when the user taps an alert.
    """

    created_by_name = serializers.SerializerMethodField()
    is_high_priority = serializers.BooleanField(read_only=True)

    class Meta:
        model = Alert
        fields = [
            'id',
            'title',
            'body',
            'category',
            'urgency',
            'status',
            'is_high_priority',
            'created_by_name',
            'recipient_count',
            'dispatched_at',
            'created_at',
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj: Alert) -> str:
        """Returns the display name of the admin who composed the alert."""
        return obj.created_by.get_display_name()


class AlertDetailSerializer(serializers.ModelSerializer):
    """
    Full alert representation used in:
    - POST /api/v1/alerts/compose/    (response after creation)
    - GET  /api/v1/alerts/<id>/       (AlertDetailView)
    - GET  /api/v1/alerts/admin/      (AdminAlertListView)

    Includes classification metadata (method, confidence) so the admin UI
    can display how the urgency was determined.
    """

    created_by = UserProfileSerializer(read_only=True)
    is_high_priority = serializers.BooleanField(read_only=True)

    class Meta:
        model = Alert
        fields = [
            'id',
            'title',
            'body',
            'category',
            'urgency',
            'classification_method',
            'classification_confidence',
            'status',
            'is_high_priority',
            'is_active',
            'created_by',
            'recipient_count',
            'dispatched_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


# ─────────────────────────────────────────────────────────────────────────────
# Student Acknowledge Input
# ─────────────────────────────────────────────────────────────────────────────

class AlertAcknowledgeSerializer(serializers.Serializer):
    """
    Validates the payload sent by Flutter when the student taps "Acknowledge"
    on a Critical or High urgency full-screen overlay (F-05).

    The channel tells the backend which delivery path actually reached
    the device — needed for accurate delivery analytics.
    """

    channel = serializers.ChoiceField(
        choices=DeliveryLog.Channel.choices,
        help_text=(
            'Delivery channel that delivered this alert to the device. '
            'One of: fcm, lan_websocket, offline_stored.'
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Admin Delivery Status
# ─────────────────────────────────────────────────────────────────────────────

class DeliveryLogSerializer(serializers.ModelSerializer):
    """
    Per-user delivery record nested inside AlertDeliveryStatusSerializer.

    Exposes enough information for the Admin Delivery Status Screen (F-12)
    to show: who received the alert, via which channel, whether they
    acknowledged it, and when each event happened.
    """

    user_display_name = serializers.SerializerMethodField()
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_role = serializers.CharField(source='user.role', read_only=True)
    is_acknowledged = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryLog
        fields = [
            'id',
            'user_display_name',
            'user_email',
            'user_role',
            'channel',
            'delivered_at',
            'acknowledged_at',
            'is_acknowledged',
            'fcm_message_id',
            'created_at',
        ]
        read_only_fields = fields

    def get_user_display_name(self, obj: DeliveryLog) -> str:
        return obj.user.get_display_name()

    def get_is_acknowledged(self, obj: DeliveryLog) -> bool:
        """True when the user tapped Acknowledge on a Critical/High overlay."""
        return obj.acknowledged_at is not None


class AlertDeliveryStatusSerializer(serializers.ModelSerializer):
    """
    Alert detail plus a full inline delivery log.

    Used by GET /api/v1/alerts/<id>/delivery-status/ (AlertDeliveryStatusView).

    Computes delivery summary statistics (total, delivered, acknowledged)
    in Python from the prefetched delivery_logs queryset — avoids an extra
    round-trip since the logs are already prefetched in the view.
    """

    created_by = UserProfileSerializer(read_only=True)
    delivery_logs = DeliveryLogSerializer(many=True, read_only=True)
    delivery_summary = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = [
            'id',
            'title',
            'body',
            'category',
            'urgency',
            'classification_method',
            'classification_confidence',
            'status',
            'is_active',
            'created_by',
            'recipient_count',
            'dispatched_at',
            'created_at',
            'updated_at',
            'delivery_summary',
            'delivery_logs',
        ]
        read_only_fields = fields

    def get_delivery_summary(self, obj: Alert) -> dict:
        """
        Computes high-level delivery stats from the prefetched delivery_logs.

        Returns:
            total         — number of delivery log rows (may be < recipient_count
                            if some deliveries are still in flight)
            delivered     — logs with a non-null delivered_at
            acknowledged  — logs with a non-null acknowledged_at
            pending       — logs where delivered_at is still null
            channels      — breakdown by delivery channel
        """
        logs = obj.delivery_logs.all()

        total = len(logs)
        delivered = sum(1 for log in logs if log.delivered_at is not None)
        acknowledged = sum(1 for log in logs if log.acknowledged_at is not None)
        pending = total - delivered

        # Channel breakdown: count how many logs came via each channel
        channel_counts: dict[str, int] = {}
        for log in logs:
            channel_counts[log.channel] = channel_counts.get(log.channel, 0) + 1

        return {
            'total': total,
            'delivered': delivered,
            'acknowledged': acknowledged,
            'pending': pending,
            'channels': channel_counts,
        }
    
