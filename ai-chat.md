Am working on a school project, i have used Django Rest Framework for the backend now i want to use React Native & EXPO for the mobile app, i previously planned using Flutter but now i have change my mind to use React Native. The project name is Campus Alert, am through with the backend and am currently on the frontend(mobile app). 


BRIEF ABOUT THE PROJECT(BUT NOTE WE NOW WANT TO USE REACT NATIVE & EXPO AND NOT FLUTTER)


1. Product Overview

1.1 What Is CampusAlert?
CampusAlert is a mobile application for Covenant University that allows administrators to send announcements and emergency alerts to all students and staff. Unlike existing channels such as email or Telegram groups, CampusAlert uses an AI-powered classification engine to automatically determine how urgent each message is and then delivers it in a way that matches that urgency level — from a silent notification for a routine update to a full-screen takeover for a fire alarm.
The app is designed to work even when the campus internet is down. As long as a device is connected to the university's Wi-Fi network, alerts can still be delivered through a local server running on that same network. If even the Wi-Fi is unavailable, the alert is stored on the device and shown automatically once connectivity is restored.

1.2 The Problem It Solves
Covenant University currently has no reliable, unified system for delivering urgent information to students. The problems with the current setup are:

•	Emails are slow, rarely checked, and cannot distinguish between a routine update and a fire alarm.
•	Telegram broadcast groups were shut down after security breaches allowed non-students to remain in official channels.
•	When the internet goes down, all digital communication fails — forcing administrators to physically walk across halls of residence to deliver urgent messages.
•	There is no system that automatically flags a message as an emergency and ensures it cannot be missed.

CampusAlert solves all of these problems in one application.

1.3 Who Uses It?

User Type	Who They Are	What They Do in the App
Administrator	Dean's office, security, ICT staff, chaplaincy	Compose and send alerts to students
Student	All enrolled Covenant University students	Receive and read alerts; view alert history
Staff	Lecturers and support staff	Receive alerts relevant to their role

 
2. Goals and Success Metrics

2.1 Goals
•	Deliver alerts to all students within seconds, regardless of network condition.
•	Automatically classify every alert into one of four urgency levels: Critical, High, Medium, or Low.
•	Ensure Critical and High alerts cannot be missed by using full-screen takeover notifications.
•	Work on the campus LAN without internet access.
•	Restrict access to verified Covenant University accounts only.
•	Replace insecure, unreliable channels like email and Telegram for official university communication.

2.2 Success Metrics

Metric	Target	How It Is Measured
XGBoost classification accuracy	≥ 80%
Test dataset evaluation
False alarm rate (non-urgent classified as Critical/High)	< 5%	Test dataset evaluation
End-to-end alert latency (internet mode)	< 2 seconds	Postman + timing logs
End-to-end alert latency (LAN mode)	< 5 seconds	Postman + timing logs
Offline alert delivery on reconnect	100% of stored alerts delivered	Manual testing
User satisfaction (UAT)	≥ 80% positive rating
Post-test survey

 
3. Urgency Classification System

3.1 The Four Urgency Levels
Every message submitted by an administrator is automatically classified into one of the following four urgency levels by the XGBoost AI model before it is delivered to students.

Urgency Level	Example Messages	Notification Behaviour	Delivery Target
Critical	Fire, explosion, armed threat, medical emergency, bomb threat, evacuation order	Full-screen takeover — cannot be dismissed without acknowledgement	Immediate — delivered within 2 seconds
High	Lockdown, power outage, serious security incident, campus-wide safety alert	Full-screen takeover with sound and vibration	Immediate
Medium	Disruption, schedule change affecting safety, health advisory	Standard heads-up notification with sound	Within 10 seconds
Low	General announcement, event reminder, routine administrative update	Silent notification in notification tray	Within 30 seconds

3.2 How Classification Works
The classification pipeline works in two steps:

Step 1 — Keyword Rule Override
Before the AI model is even called, the system checks whether the message contains any predefined critical keywords. If it does, the message is immediately classified as Critical and delivered without waiting for the AI. This ensures the fastest possible response for the most dangerous alerts.

Step 2 — XGBoost AI Classification
If no critical keyword is detected, the message text is processed using TF-IDF (Term Frequency-Inverse Document Frequency), which converts the text into a set of numbers that represent how significant each word is. These numbers are passed into the XGBoost model, which votes across hundreds of internal decision trees and outputs a predicted urgency class: Critical, High, Medium, or Low.

XGBoost was chosen over other AI models such as BERT or ChatGPT-style models because it works extremely well on small datasets, is fast enough for real-time classification, and does not require expensive servers or cloud compute to run.

3.3 Urgency Keywords
The following keywords trigger an immediate Critical classification regardless of what the rest of the message says:

Urgency Level	Example Keywords
Critical	fire, explosion, bomb, armed, shooter, weapon, evacuate, evacuation, emergency, attack, threat, lockdown, hostage, casualty, fatality, collapse
High	danger, hazard, medical, ambulance, injury, accident, power outage, gas leak, flood, security breach, police, arrest, suspect, incident, alert, warning
Medium	disruption, delay, cancelled, rescheduled, health advisory, caution, notice, advisory, unwell, closed
Low	reminder, event, announcement, update, information, schedule, note, meeting, chapel, sports, activity

 
4. Features

The table below lists every feature the system must have, along with its priority. 'Must Have' means the feature is required for the project to be considered complete. 'Should Have' means it is important but could be added in a later phase if time is short.

ID	Feature	Description	Priority
F-01	User Authentication	Only verified Covenant University students and staff can log in and receive alerts	Must Have
F-02	Alert Composition	Administrators can type and send alert messages with a title, body, and optional category tag	Must Have
F-03	XGBoost Urgency Classification	Every submitted message is automatically classified into Critical, High, Medium, or Low urgency using the XGBoost ML model	Must Have
F-04	Keyword Override	If a message contains defined critical keywords (fire, evacuate, lockdown, attack, bomb, medical emergency), it is immediately classified as Critical without waiting for ML inference	Must Have
F-05	Full-Screen Alert (Critical & High)	Critical and High urgency alerts trigger a full-screen pop-up on the recipient's device that cannot be easily dismissed	Must Have
F-06	Standard Notification (Medium & Low)	Medium and Low urgency alerts deliver as standard push notifications	Must Have
F-07	Online Delivery via FCM	When the device has internet access, alerts are delivered through Firebase Cloud Messaging	Must Have
F-08	LAN / Intranet Delivery via Socket.IO	When the device is connected to the campus Wi-Fi but has no internet, alerts are delivered over the local network through a Socket.IO server hosted on a LAN machine	Must Have
F-09	Offline Storage via SQLite	If neither internet nor LAN is available, the alert is stored locally on the device in a SQLite database and displayed when connectivity is restored	Must Have
F-10	Alert History	Students can scroll through all previously received alerts inside the app	Must Have
F-11	Admin Dashboard	Administrators have a separate screen to compose alerts and view delivery status	Must Have
F-12	Delivery Status Tracking	The system records whether each alert was delivered via FCM, LAN, or stored offline	Should Have
F-13	Simulated LAN Demo Mode	For testing purposes, the LAN delivery can be simulated by connecting all devices to the same Wi-Fi hotspot with the backend running on a laptop on the same network	Must Have

 
5. Alert Delivery Pipeline

CampusAlert uses three delivery methods. The system tries each method in order until the alert is successfully delivered.

Method 1 — Internet (Firebase Cloud Messaging)
When the student's device has internet access, alerts are pushed through Firebase Cloud Messaging (FCM), which is Google's free push notification service. FCM is fast, reliable, and delivers even when the app is closed in the background. This is the primary delivery method.

Method 2 — Campus LAN (Socket.IO)
When the internet is down but the device is still connected to the campus Wi-Fi, alerts are delivered through a Socket.IO server running on a local machine (a laptop or server) connected to the same Wi-Fi network. Socket.IO creates a persistent real-time connection between the app and the server, allowing instant messaging without the internet.
For the purposes of this academic project, this is simulated by connecting all test devices and the backend laptop to the same Wi-Fi hotspot. This demonstrates the functionality without needing access to Covenant University's real internal network infrastructure.

Method 3 — Offline Storage (SQLite)
If neither internet nor LAN is available, the alert is saved into a local SQLite database on the student's device. As soon as the device reconnects to either the internet or the campus LAN, the stored alerts are automatically displayed to the student. No alert is lost.

Delivery Flow Summary

Step	Action	Condition	Result
1	Admin submits alert	Any	Message received by backend
2	Keyword check	Always runs first	If keyword found → Critical instantly

3	XGBoost classification	No keyword override triggered	Urgency level assigned (Critical/High/Medium/Low)
4a	FCM delivery	Device has internet	Alert delivered as push notification or full-screen
4b	Socket.IO delivery	No internet, LAN available	Alert delivered over campus Wi-Fi
4c	SQLite storage	No internet, no LAN	Alert stored; delivered on reconnect
5	Alert displayed	Critical/High urgency	Full-screen pop-up on student device
5	Alert displayed	Medium/Low urgency	Standard notification

 
6. App Screens

The following screens must be designed and built in the mobile application.

Screen	User	Description
Login Screen	All users	University email and password login; only verified accounts are accepted
Student Home / Alert Feed	Students	List of all received alerts showing urgency level, title, time, and read status
Full-Screen Alert Pop-Up	Students (auto-triggered)	Takes over the entire screen when a Critical or High urgency alert arrives; shows alert title, body, urgency badge, and a dismiss/acknowledge button
Standard Notification	Students (auto-triggered)	Normal push notification for Medium and Low urgency alerts
Alert Detail View	Students	Full text of any alert when tapped from the feed
Admin Home	Administrators	Overview of recent alerts sent and their delivery statuses
Compose Alert Screen	Administrators	Text fields for title and message body; submit button that triggers classification and delivery
Delivery Status Screen	Administrators	Shows which delivery channel was used (FCM / LAN / Offline) for each alert
Settings Screen	All users	Profile info, notification preferences, logout




BACKEND STRUCTURE

website/
├── .env
├── Readme.MD
├── accounts
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── migrations
│   │   ├── 0001_initial.py
│   │   └── __init__.py
│   ├── models.py
│   ├── serializers.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
├── alerts
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── consumers.py
│   ├── migrations
│   │   ├── 0001_initial.py
│   │   └── __init__.py
│   ├── models.py
│   ├── permissions.py
│   ├── serializers.py
│   ├── services
│   │   ├── __init__.py
│   │   ├── classifier.py
│   │   ├── delivery.py
│   │   └── fcm.py
│   ├── tasks.py
│   ├── tests
│   │   ├── __init__.py
│   │   ├── test_classifier.py
│   │   └── test_views.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
├── core
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── exceptions.py
│   ├── migrations
│   │   └── __init__.py
│   ├── models.py
│   ├── tests.py
│   └── views.py
├── logs
│   └── django.log
├── manage.py
├── ml
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── evaluate.py
│   ├── metadata.json
│   ├── migrations
│   │   └── __init__.py
│   ├── model.pkl
│   ├── models.py
│   ├── prepare_dataset.py
│   ├── tests.py
│   ├── train.py
│   ├── vectorizer.pkl
│   └── views.py
├── requirements.txt
├── static
└── website
    ├── __init__.py
    ├── asgi.py
    ├── celery.py
    ├── settings.py
    ├── urls.py
    └── wsgi.py




Am through with the backend apis, these are the endpoints

# campusalert/accounts/urls.py

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    DeviceTokenUpdateView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    RegisterView,
)

app_name = 'accounts'

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('device/', DeviceTokenUpdateView.as_view(), name='device_token_update'),
    path('password/change/', PasswordChangeView.as_view(), name='password_change'),
]


# campusalert/alerts/urls.py

from django.urls import path

from .views import (
    AdminAlertListView,
    AlertAcknowledgeView,
    AlertComposeView,
    AlertDeliveryStatusView,
    AlertDetailView,
    AlertFeedView,
    MissedAlertsView,
)

app_name = 'alerts'

urlpatterns = [
    # Student & Staff endpoints
    path('', AlertFeedView.as_view(), name='feed'),
    path('missed/', MissedAlertsView.as_view(), name='missed'),
    path('<uuid:pk>/', AlertDetailView.as_view(), name='detail'),
    path('<uuid:pk>/acknowledge/', AlertAcknowledgeView.as_view(), name='acknowledge'),

    # Admin-only endpoints
    path('compose/', AlertComposeView.as_view(), name='compose'),
    path('admin/', AdminAlertListView.as_view(), name='admin_list'),
    path('<uuid:pk>/delivery-status/', AlertDeliveryStatusView.as_view(), name='delivery_status'),
]



# campusalert/accounts/views.py

"""
Accounts API views for CampusAlert.

Endpoints:
    POST   /api/v1/accounts/register/          — Create new Covenant University account
    POST   /api/v1/accounts/login/             — Obtain JWT access + refresh tokens
    POST   /api/v1/accounts/token/refresh/     — Refresh access token
    POST   /api/v1/accounts/logout/            — Blacklist refresh token (logout)
    GET    /api/v1/accounts/me/                — Authenticated user profile
    PATCH  /api/v1/accounts/device/            — Update FCM device token
    POST   /api/v1/accounts/password/change/   — Change password
"""

import logging

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import (
    FCMTokenUpdateSerializer,
    PasswordChangeSerializer,
    UserProfileSerializer,
    UserRegistrationSerializer,
)

User = get_user_model()
logger = logging.getLogger('campusalert.accounts')


class RegisterView(APIView):
    """
    POST /api/v1/accounts/register/

    Creates a new CampusAlert account for a verified Covenant University student or staff member.
    Validates the Covenant University email domain before creating the account.
    Returns JWT tokens immediately so the user does not need to log in after registration.
    """

    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Issue JWT tokens immediately so the user is logged in on first registration
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                'user': UserProfileSerializer(user).data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    """
    POST /api/v1/accounts/login/

    Extends simplejwt's TokenObtainPairView to include the user profile in the response.
    This saves Flutter from making a second API call after login.

    Expected payload: { "username": "...", "password": "..." }
    Returns:          { "access": "...", "refresh": "...", "user": {...} }

    Protected by django-axes: accounts are locked after 5 failed attempts.
    """

    def post(self, request, *args, **kwargs) -> Response:
        response = super().post(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            # Attach user profile to the token response
            try:
                user = User.objects.get(username=request.data.get('username', ''))
                response.data['user'] = UserProfileSerializer(user).data
                logger.info('User logged in: %s', user.username)
            except User.DoesNotExist:
                # Token was issued; user lookup failure is non-fatal — just skip the profile
                logger.warning('Could not fetch profile for login response (user not found).')

        return response


class LogoutView(APIView):
    """
    POST /api/v1/accounts/logout/

    Blacklists the provided refresh token so it can no longer be used.
    The access token expires naturally after its lifetime.

    Expected payload: { "refresh": "<refresh_token>" }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': True, 'message': 'refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            logger.info('User logged out: %s', request.user.username)
            return Response({'message': 'Logged out successfully.'}, status=status.HTTP_200_OK)
        except TokenError:
            # Token is already expired or invalid — treat as logged out
            return Response({'message': 'Logged out.'}, status=status.HTTP_200_OK)


class MeView(APIView):
    """
    GET /api/v1/accounts/me/

    Returns the authenticated user's profile.
    Flutter uses this to refresh user state after token renewal.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DeviceTokenUpdateView(APIView):
    """
    PATCH /api/v1/accounts/device/

    Updates the FCM device token for the authenticated user.
    Flutter must call this endpoint on every app launch because FCM tokens
    can be rotated by Firebase at any time. Stale tokens cause failed FCM delivery.

    Expected payload: { "fcm_token": "<firebase_device_token>" }
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request) -> Response:
        serializer = FCMTokenUpdateSerializer(
            instance=request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        logger.info('FCM token updated for user: %s', request.user.username)
        return Response({'message': 'Device token updated.'}, status=status.HTTP_200_OK)


class PasswordChangeView(APIView):
    """
    POST /api/v1/accounts/password/change/

    Allows an authenticated user to change their own password.
    Requires the current password for verification.
    Invalidates all existing sessions by resetting the session after the change.

    Expected payload:
        { "current_password": "...", "new_password": "...", "new_password_confirm": "..." }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({'message': 'Password changed successfully.'}, status=status.HTTP_200_OK)



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


# campusalert/accounts/models.py

"""
Custom User model for CampusAlert.

Extends Django's AbstractUser with:
- UUID7 primary key (replaces Django's default integer pk)
- Role-based access: Administrator, Student, Staff
- FCM token storage for push notification delivery
- Covenant University email domain enforcement
- is_verified flag for account approval workflow
"""

import uuid6
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    CampusAlert user model.

    Replaces Django's integer pk with UUID7. Adds role, FCM device token,
    and verification flag for Covenant University access control.

    Key fields:
        role         — determines admin vs student/staff UI and permissions
        fcm_token    — updated by Flutter app on each login; used for FCM delivery
        is_verified  — manually or automatically verified Covenant University account
    """

    class Role(models.TextChoices):
        ADMIN = 'admin', _('Administrator')
        STUDENT = 'student', _('Student')
        STAFF = 'staff', _('Staff')

    # Override the default integer pk with UUID7
    id = models.UUIDField(
        primary_key=True,
        default=uuid6.uuid7,
        editable=False,
        help_text='UUID7 primary key — time-sortable and globally unique.',
    )

    # Role determines what the user can do in the app
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.STUDENT,
        db_index=True,
        help_text='User role. Administrators can compose and send alerts.',
    )

    # FCM device token — updated by Flutter on each app launch.
    # Nullable because users may not have logged into the app yet.
    fcm_token = models.TextField(
        null=True,
        blank=True,
        help_text=(
            'Firebase Cloud Messaging device token for push notification delivery. '
            'Updated by the Flutter app on every login.'
        ),
    )

    # Optional department for staff/admin routing in future phases
    department = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Faculty or department name. Optional.',
    )

    # Covenant University student/staff ID
    cu_id = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text='Covenant University matriculation number or staff ID.',
    )

    # Verified flag: True once the Covenant University email domain is confirmed
    is_verified = models.BooleanField(
        default=False,
        help_text='True when the account email domain has been verified.',
    )

    # created_at and updated_at are provided by AbstractUser via date_joined and last_login.
    # We add explicit created_at for consistency with TimeStampedModel pattern.
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['role'], name='user_role_idx'),
            models.Index(fields=['is_verified', 'role'], name='user_verified_role_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.get_full_name() or self.username} ({self.role})'

    @property
    def is_admin(self) -> bool:
        """True if this user can compose and send alerts."""
        return self.role == self.Role.ADMIN or self.is_staff or self.is_superuser

    def get_display_name(self) -> str:
        """Returns full name if available, otherwise username."""
        return self.get_full_name() or self.username
    






FRONTEND STRUCTURE 

lib/
├── app_state.dart
├── core
│   ├── api_client.dart
│   ├── local_db.dart
│   └── websocket_client.dart
├── features
│   ├── admin
│   │   ├── admin_home_screen.dart
│   │   ├── compose_alert_screen.dart
│   │   └── delivery_status_screen.dart
│   ├── alerts
│   │   ├── alert_detail_screen.dart
│   │   ├── alert_feed_screen.dart
│   │   └── alert_repository.dart
│   └── auth
│       ├── auth_repository.dart
│       └── login_screen.dart
├── main.dart
├── models
│   ├── alert_model.dart
│   └── user_model.dart
├── project_tree.py
└── services
    ├── connectivity_service.dart
    ├── fcm_service.dart
    └── sync_service.dart







THESE IS WHAT THE FRONTEND SUPPOSED TO BE

Phase 4 — Flutter App (complete)
Core layer
FileWhat it doeslib/core/api_client.dartDio + QueuedInterceptorsWrapper — attaches Bearer token, silently refreshes on 401, calls onLogout on failure, setServerUrl() for LAN switchinglib/core/local_db.dartSQLite — upsertAlert, upsertAlerts (batch), getLastAlertTimestamp for sync, deleteOlderThan for housekeeping, unread countlib/core/websocket_client.dartWebSocketChannel connecting to ws://<ip>:8000/ws/alerts/?token=<jwt> — routes new_alert to callback, answers Django heartbeat pings with pong
Services
FileWhat it doeslib/services/fcm_service.dart4 Android notification channels (campusalert_critical → campusalert_low), background message handler, fullScreenIntent: true for Critical, token streamlib/services/connectivity_service.dart3-state enum: internet / lanOnly / offline — triggers reconnect logic in AlertRepositorylib/services/sync_service.dartsyncMissedAlerts() — reads getLastAlertTimestamp(), calls GET /api/v1/alerts/missed/, bulk-upserts to SQLite, prunes 30-day-old alerts
Features
FileWhat it doeslib/features/auth/auth_repository.dartLogin (saves JWT, registers FCM token), register, getProfile (session restore), logout (blacklists refresh token)lib/features/auth/login_screen.dartFull UI — validation, error banner, "Change Server URL" dialog for LAN IP switchinglib/features/alerts/alert_repository.dartWires FCM + WebSocket + Sync into one stream; fetchAlertFeed falls back to SQLite when offline; acknowledgeAlert calls Djangolib/features/alerts/alert_feed_screen.dartUrgency filter chips, unread badge, timeago timestamps, live stream prepending new alertslib/features/alerts/alert_detail_screen.dartFull text, delivery channel badge (FCM/LAN/Offline), metadata rowlib/features/alerts/full_screen_alert.dartPulsing icon animation, WillPopScope (back button blocked), HapticFeedback.heavyImpact(), portrait lock, "Acknowledge" calls Djangolib/features/admin/admin_home_screen.dartAdmin dashboard, FAB → ComposeAlertScreenlib/features/admin/compose_alert_screen.dartCategory chips, classification result dialog showing urgency + method (keyword_override vs xgboost)lib/features/admin/delivery_status_screen.dartProgress bars per channel, stat badges, channel breakdown
Root wiring
FileWhat it doeslib/models/UserModel, AlertModel (SQLite + JSON serialisation), DeliveryStatusModellib/app_state.dartChangeNotifier — single source of truth; init() restores session; _onNewAlertArrived prepends to feed and signals full-screen overlaylib/main.dartFirebase init, all dependencies constructed and injected, _RootScreen auth gate + role routing, pendingFullScreenAlert observerandroid/AndroidManifest.xmlUSE_FULL_SCREEN_INTENT, WAKE_LOCK, showWhenLocked, turnScreenOn, usesCleartextTraffic for LAN demo
Phase 5 — Integration & Testing
INTEGRATION_TESTING.md contains:

Test 4.1 — FCM internet path with timer measurement (< 2s target)
Test 4.2 — LAN WebSocket path with wscat verification commands (< 5s target)
Test 4.3 — Offline → reconnect sync with 100% delivery verification
Latency measurement script — cross-references Django dispatch log with device receipt
UAT scenarios — 4 real-user test scripts covering all urgency levels
Classification accuracy spot-check table — 6 test messages with expected urgency + method
Known issues table — 6 edge cases with mitigations
Production checklist — HTTPS, Nginx, PgBouncer, battery whitelisting






Phase 4 — Flutter App (Week 4)
Login screen → JWT stored in flutter_secure_storage
FCM token registration on startup → PATCH /api/v1/accounts/device/
Alert feed screen pulling from REST API
WebSocket client connecting to Django consumer
SQLite offline cache + reconnect sync
Full-screen takeover for Critical/High


Phase 5 — Integration & Testing (Week 5)

Connect Flutter to Django on same Wi-Fi hotspot (simulated LAN)
Test all 3 delivery paths end-to-end: FCM → WebSocket → offline→reconnect
Measure latency (target: <2s internet, <5s LAN)
UAT with test users



lib/
├── main.dart
├── core/
│   ├── api_client.dart          # Dio HTTP client, JWT interceptor
│   ├── websocket_client.dart    # web_socket_channel package
│   └── local_db.dart           # sqflite — offline alert cache
├── features/
│   ├── auth/
│   │   ├── login_screen.dart
│   │   └── auth_repository.dart
│   ├── alerts/
│   │   ├── alert_feed_screen.dart      # Student home
│   │   ├── alert_detail_screen.dart
│   │   ├── full_screen_alert.dart      # Critical/High takeover
│   │   └── alert_repository.dart      # REST + WebSocket + SQLite
│   └── admin/
│       ├── admin_home_screen.dart
│       ├── compose_alert_screen.dart
│       └── delivery_status_screen.dart
└── services/
    ├── fcm_service.dart         # firebase_messaging package
    ├── connectivity_service.dart # connectivity_plus package
    └── sync_service.dart        # fetches missed alerts on reconnect




dependencies:

  dio: ^5.4.0                    # HTTP client
  firebase_messaging: ^14.9.0    # FCM
  web_socket_channel: ^2.4.0     # LAN WebSocket
  sqflite: ^2.3.0                # Offline SQLite
  connectivity_plus: ^6.0.0      # Network detection
  flutter_local_notifications: ^17.0.0  # Show notifications
  flutter_secure_storage: ^9.0.0 # Store JWT securely
  provider: ^6.1.0               # State management





THESE ARE CODES FROM MY FRONTEND CURRENTLY 

# campusalert_flutter/pubspec.yaml

name: campusalert
description: CampusAlert — Covenant University real-time alert system with XGBoost urgency classification.
publish_to: 'none'
version: 1.0.0+1

environment:
  sdk: ^3.11.3

dependencies:
  flutter:
    sdk: flutter


  # ─── HTTP & Auth ───────────────────────────────────────────
  dio: ^5.4.0                          # HTTP client with interceptors
  flutter_secure_storage: ^9.0.0       # Encrypted JWT storage (Keystore/Keychain)

  # ─── Firebase / FCM ────────────────────────────────────────
  firebase_core: ^2.27.0
  firebase_messaging: ^14.9.0          # Push notification delivery (F-07)

  # ─── Real-time / LAN ───────────────────────────────────────
  web_socket_channel: ^2.4.0           # Campus LAN delivery via Django ASGI (F-08)

  # ─── Local Storage / Offline ───────────────────────────────
  sqflite: ^2.3.0                      # Offline alert cache (F-09)
  path: ^1.8.3                         # SQLite DB path resolution

  # ─── Network Detection ─────────────────────────────────────
  connectivity_plus: ^6.0.0            # Triggers offline→online sync (F-09)

  # ─── Notifications ─────────────────────────────────────────
  flutter_local_notifications: ^17.0.0 # Show in-app banners & full-screen alerts

  # ─── State Management ──────────────────────────────────────
  provider: ^6.1.0                     # Dependency injection + state

  # ─── UI Utilities ──────────────────────────────────────────
  timeago: ^3.6.0                      # Relative timestamps ("2 minutes ago")
  cached_network_image: ^3.3.1         # Avatar images with cache
  shimmer: ^3.0.0                      # Loading skeleton UI
  intl: ^0.19.0                        # Date formatting

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^6.0.0
  mockito: ^5.4.4
  build_runner: ^2.4.8


flutter:
  uses-material-design: true
  assets:
    - assets/images/
    - assets/sounds/



Start by providing the complete React native project structure showing all folders, files and roles/function in the general project, before moving into writting the actual codes. 

For every single file you write codes in, in the beginning of the file, add label(showing the path to the file) for me to easily identity which codes goes into which file or which file has which code.  

Make all codes modular, DRY, secure, production ready, no placeholders code, no TODO, no dummy codes,  all codes should be production ready, professional, well documented and commented, maintainable, optimize, performant, easy to read etc

Empasis on comment and documentations so that i understand the role or each files and the functions under each file. 