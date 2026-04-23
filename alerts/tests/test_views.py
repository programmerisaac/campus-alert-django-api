# campusalert/alerts/tests/test_views.py

"""
Integration tests for the alerts API views — Phase 3.

Tests cover:
- Alert composition by admin (POST /api/v1/alerts/compose/)
- Alert feed for students (GET /api/v1/alerts/)
- Missed alerts sync (GET /api/v1/alerts/missed/)
- Alert acknowledgement (POST /api/v1/alerts/<id>/acknowledge/)
- Permission enforcement (students cannot compose; unverified users blocked)

Run with:
    python manage.py test alerts.tests.test_views
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from alerts.models import Alert, DeliveryLog

User = get_user_model()


def get_auth_headers(user) -> dict:
    """Returns Authorization header dict for a given user."""
    refresh = RefreshToken.for_user(user)
    return {'HTTP_AUTHORIZATION': f'Bearer {refresh.access_token}'}


def make_user(username: str, role: str = 'student', is_verified: bool = True) -> User:
    """Creates a verified test user."""
    return User.objects.create_user(
        username=username,
        email=f'{username}@covenantuniversity.edu.ng',
        password='StrongTestPass123!',
        role=role,
        is_verified=is_verified,
        first_name='Test',
        last_name='User',
    )


def make_dispatched_alert(created_by: User, urgency: str = 'low', **kwargs) -> Alert:
    """Creates a dispatched alert for testing the feed and detail views."""
    return Alert.objects.create(
        title=kwargs.get('title', 'Test Alert'),
        body=kwargs.get('body', 'This is a test alert body for automated testing.'),
        category=kwargs.get('category', Alert.Category.GENERAL),
        urgency=urgency,
        classification_method=Alert.ClassificationMethod.XGBOOST,
        classification_confidence=0.85,
        created_by=created_by,
        status=Alert.Status.DISPATCHED,
        dispatched_at=timezone.now(),
        recipient_count=100,
    )


class AlertComposeViewTests(APITestCase):
    """Tests for POST /api/v1/alerts/compose/"""

    def setUp(self):
        self.admin = make_user('admin1', role='admin')
        self.student = make_user('student1', role='student')
        self.unverified = make_user('unverified1', role='admin', is_verified=False)
        self.url = '/api/v1/alerts/compose/'

    @patch('alerts.tasks.dispatch_alert_task.delay')
    @patch('alerts.views.classify_alert')
    def test_admin_can_compose_alert(self, mock_classify, mock_delay):
        """Verified admin successfully composes an alert."""
        mock_classify.return_value = ('low', 'xgboost', 0.87)
        mock_delay.return_value = None

        response = self.client.post(
            self.url,
            {'title': 'Library Update', 'body': 'New library hours effective Monday.', 'category': 'general'},
            **get_auth_headers(self.admin),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['urgency'], 'low')
        self.assertEqual(response.data['classification_method'], 'xgboost')
        self.assertTrue(mock_delay.called)

    @patch('alerts.tasks.dispatch_alert_task.delay')
    @patch('alerts.views.classify_alert')
    def test_critical_keyword_classified_as_critical(self, mock_classify, mock_delay):
        """Keyword override produces critical urgency in the API response."""
        mock_classify.return_value = ('critical', 'keyword_override', None)
        mock_delay.return_value = None

        response = self.client.post(

