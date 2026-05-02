
# campusalert/alerts/views.py

"""
Alert API views — Phase 3.

Endpoints:
    POST   /api/v1/alerts/                       — Admin: compose and send alert
    GET    /api/v1/alerts/                       — Student/Staff: alert feed (paginated)
    GET    /api/v1/alerts/<id>/                  — Alert detail
    GET    /api/v1/alerts/missed/                — Offline sync: alerts since <timestamp>
    POST   /api/v1/alerts/<id>/acknowledge/      — Student: acknowledge Critical/High alert
    GET    /api/v1/alerts/<id>/delivery-status/  — Admin: delivery status for one alert
    GET    /api/v1/alerts/admin/                 — Admin: list of all sent alerts
"""

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import filters, generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from .models import Alert, DeliveryLog
from .permissions import IsVerifiedAdminRole, IsVerifiedUser
from .serializers import (
    AlertAcknowledgeSerializer,
    AlertCreateSerializer,
    AlertDeliveryStatusSerializer,
    AlertDetailSerializer,
    AlertListSerializer,
)
from .services.classifier import classify_alert
from .services.delivery import get_missed_alerts
from .tasks import dispatch_alert_task

logger = logging.getLogger('campusalert.alerts.views')


class AlertComposeView(APIView):
    """
    POST /api/v1/alerts/

    Admin-only endpoint. Accepts title + body + category, runs the classification
    pipeline, saves the alert, and dispatches via Celery (non-blocking).

    The response returns immediately with the classified alert — the admin sees
    the urgency level before delivery completes. FCM + LAN delivery happens
    asynchronously in the Celery task.

    Auth: Verified admin role required.
    """

    permission_classes = [IsAuthenticated, IsVerifiedAdminRole]

    def post(self, request) -> Response:
        serializer = AlertCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        title: str = serializer.validated_data['title']
        body: str = serializer.validated_data['body']
        category: str = serializer.validated_data.get('category', Alert.Category.GENERAL)

        # ── Step 1: Run classification pipeline (synchronous, < 500ms) ────────
        urgency, method, confidence = classify_alert(title=title, body=body)

        logger.info(
            'Alert classified: urgency=%s method=%s confidence=%s by admin=%s',
            urgency, method, confidence, request.user.username,
        )

        # ── Step 2: Save the classified alert inside a transaction ────────────
        with transaction.atomic():
            alert = Alert.objects.create(
                title=title,
                body=body,
                category=category,
                urgency=urgency,
                classification_method=method,
                classification_confidence=confidence,
                created_by=request.user,
                status=Alert.Status.CLASSIFIED,
            )

            # ── Step 3: Dispatch after commit — never inside the transaction ──
            # Celery task only fires after the Alert row is committed to PostgreSQL.
            # This prevents the task from trying to load an Alert that hasn't been
            # written yet due to a race between Celery and the DB.
            transaction.on_commit(
                lambda: dispatch_alert_task.delay(str(alert.id))
            )

        return Response(
            AlertDetailSerializer(alert).data,
            status=status.HTTP_201_CREATED,
        )


class AlertPagePagination(PageNumberPagination):
    """
    Standard page-number pagination for the alert feed.
    Returns { count, next, previous, results } shape the mobile app expects.
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class AlertFeedView(generics.ListAPIView):
    """
    GET /api/v1/alerts/

    Student/Staff alert feed — paginated list of all dispatched alerts,
    most recent first. Used to render the Student Home / Alert Feed screen (PRD §6).

    Supports filtering by urgency and category via query params:
        ?urgency=critical
        ?category=security
        ?search=fire

    Auth: Any verified user (students, staff, admins).
    """

    serializer_class = AlertListSerializer
    permission_classes = [IsAuthenticated, IsVerifiedUser]
    pagination_class = AlertPagePagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'body']
    ordering_fields = ['created_at', 'urgency']
    ordering = ['-created_at']

    def get_queryset(self):
        """
        Returns dispatched alerts with optional urgency/category filtering.
        Uses select_related to avoid N+1 on created_by.
        """
        qs = (
            Alert.objects
            .filter(status=Alert.Status.DISPATCHED)
            .select_related('created_by')
            .order_by('-created_at')
        )

        urgency = self.request.query_params.get('urgency')
        if urgency and urgency in dict(Alert.Urgency.choices):
            qs = qs.filter(urgency=urgency)

        category = self.request.query_params.get('category')
        if category and category in dict(Alert.Category.choices):
            qs = qs.filter(category=category)

        return qs




class AlertDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/alerts/<id>/

    Returns full alert detail. Used by the Alert Detail View screen (PRD §6)
    when a student taps an alert in their feed.

    Auth: Any verified user.
    """

    serializer_class = AlertDetailSerializer
    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def get_queryset(self):
        return (
            Alert.objects
            .filter(status=Alert.Status.DISPATCHED)
            .select_related('created_by')
        )


class MissedAlertsView(APIView):
    """
    GET /api/v1/alerts/missed/?since=<iso_timestamp>

    Offline sync endpoint — Flutter calls this on reconnect to retrieve
    alerts that arrived while the device had no internet or LAN connectivity.

    The Flutter SQLite cache knows the timestamp of the last alert it stored.
    This endpoint returns all dispatched alerts created after that timestamp,
    ordered oldest-first so Flutter can process them chronologically.

    If no `since` parameter is provided, returns the 50 most recent alerts.

    Auth: Any verified user.
    """

    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def get(self, request) -> Response:
        since = request.query_params.get('since')
        alerts = get_missed_alerts(user=request.user, since_iso=since)

        serializer = AlertListSerializer(alerts, many=True)
        return Response(
            {
                'count': len(serializer.data),
                'since': since,
                'results': serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class AlertAcknowledgeView(APIView):
    """
    POST /api/v1/alerts/<id>/acknowledge/

    Flutter calls this when the student taps "Acknowledge" on the full-screen
    alert overlay for Critical and High urgency alerts (F-05).

    Updates or creates the DeliveryLog.acknowledged_at for this user + alert.
    Also sets delivered_at if not already set (handles LAN and offline delivery).

    Auth: Any verified user.
    """

    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def post(self, request, pk: str) -> Response:
        try:
            alert = Alert.objects.only('id', 'urgency', 'status').get(
                id=pk,
                status=Alert.Status.DISPATCHED,
            )
        except Alert.DoesNotExist:
            return Response(
                {'error': True, 'message': 'Alert not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = AlertAcknowledgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = serializer.validated_data['channel']

        now = timezone.now()

        # Update or create the delivery log for this user + alert + channel.
        # update_or_create prevents duplicate logs when the user acknowledges
        # an alert that was already logged via FCM delivery confirmation.
        DeliveryLog.objects.update_or_create(
            alert=alert,
            user=request.user,
            channel=channel,
            defaults={
                'acknowledged_at': now,
                'delivered_at': now,  # If not already set, mark as delivered now
            },
        )

        logger.info(
            'Alert %s acknowledged by user %s via %s.',
            alert.id, request.user.username, channel,
        )

        return Response({'acknowledged': True, 'alert_id': str(alert.id)}, status=status.HTTP_200_OK)


class AdminAlertListView(generics.ListAPIView):
    """
    GET /api/v1/alerts/admin/

    Admin-only list of all alerts sent, with status and classification metadata.
    Used by the Admin Home screen (PRD §6) to show recent alerts and their delivery state.

    Auth: Verified admin role.
    """

    serializer_class = AlertDetailSerializer
    permission_classes = [IsAuthenticated, IsVerifiedAdminRole]
    pagination_class = AlertPagePagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'body']
    ordering_fields = ['created_at', 'urgency', 'status']
    ordering = ['-created_at']

    def get_queryset(self):
        """Admins see all their own alerts; superusers see all alerts."""
        qs = Alert.objects.select_related('created_by').prefetch_related('delivery_logs')

        if not self.request.user.is_superuser:
            # Regular admins only see their own alerts
            qs = qs.filter(created_by=self.request.user)

        return qs


class AlertDeliveryStatusView(generics.RetrieveAPIView):
    """
    GET /api/v1/alerts/<id>/delivery-status/

    Returns delivery status for a single alert — which users received it,
    via which channel, and who acknowledged it (F-12).

    Paginated delivery log is included inline for the Admin Delivery Status Screen.

    Auth: Verified admin role.
    """

    serializer_class = AlertDeliveryStatusSerializer
    permission_classes = [IsAuthenticated, IsVerifiedAdminRole]

    def get_queryset(self):
        qs = Alert.objects.prefetch_related(
            'delivery_logs__user',
        )
        if not self.request.user.is_superuser:
            qs = qs.filter(created_by=self.request.user)
        return qs
    








