# campusalert/alerts/permissions.py

"""
DRF permission classes for the alerts app.

IsVerifiedUser       — grants access to any authenticated user whose account
                       has been verified (is_verified=True). Covers students,
                       staff, and administrators. Used on all student-facing
                       alert endpoints.

IsVerifiedAdminRole  — grants access only to verified users with the
                       Administrator role (role='admin'), Django staff flag,
                       or superuser status. Used on admin-only compose,
                       list, and delivery-status endpoints.
"""

import logging

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

logger = logging.getLogger('campusalert.alerts.permissions')


class IsVerifiedUser(BasePermission):
    """
    Allows access to any authenticated user whose is_verified flag is True.

    Rejects:
    - Unauthenticated requests (handled upstream by IsAuthenticated, but
      guarded here too for defence-in-depth)
    - Accounts that have not completed email domain verification

    Used on: AlertFeedView, AlertDetailView, MissedAlertsView,
             AlertAcknowledgeView
    """

    message = 'Your account must be verified to access this resource.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        """
        Returns True only when the requesting user is authenticated
        and their is_verified flag is set.
        """
        if not request.user or not request.user.is_authenticated:
            return False

        if not request.user.is_verified:
            logger.warning(
                'Unverified user %s attempted to access %s.',
                request.user.username,
                request.path,
            )
            return False

        return True


class IsVerifiedAdminRole(BasePermission):
    """
    Allows access only to verified administrators.

    A user qualifies when ANY of the following is true:
    - role == 'admin'  (CampusAlert Administrator)
    - is_staff == True (Django staff — used for superadmin access to /admin/)
    - is_superuser == True

    Additionally, is_verified must be True. A superuser with is_verified=False
    is still rejected; superusers must verify their accounts first.

    Used on: AlertComposeView, AdminAlertListView, AlertDeliveryStatusView
    """

    message = 'You must be a verified administrator to perform this action.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        """
        Returns True when the user is authenticated, verified, and holds
        an administrator-level role.
        """
        if not request.user or not request.user.is_authenticated:
            return False

        if not request.user.is_verified:
            logger.warning(
                'Unverified user %s attempted admin action on %s.',
                request.user.username,
                request.path,
            )
            return False

        # is_admin property on User covers role=='admin', is_staff, and is_superuser
        if not request.user.is_admin:
            logger.warning(
                'Non-admin user %s (role=%s) attempted admin action on %s.',
                request.user.username,
                request.user.role,
                request.path,
            )
            return False

        return True


