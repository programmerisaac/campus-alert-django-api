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
    

