# campusalert/accounts/serializers.py

"""
Serializers for the accounts app.

Covers:
- User registration with Covenant University domain validation
- User profile (read-only for students, role-aware)
- FCM device token update (called by Flutter on every app launch)
- Password change
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()
logger = logging.getLogger('campusalert.accounts')


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Handles new user registration.

    Enforces:
    - Covenant University email domain
    - Password confirmation and strength validation
    - Role defaults to 'student' (admins must be manually assigned by a superuser)
    """

    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
    )

    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'first_name',
            'last_name',
            'cu_id',
            'department',
            'role',
            'password',
            'password_confirm',
        ]
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
            'email': {'required': True},
            # Students cannot self-assign admin role
            'role': {'read_only': True},
        }

    def validate_email(self, value: str) -> str:
        """
        Rejects emails not from the Covenant University domain.
        This is the primary access control gate for the entire system.
        """
        domain = settings.COVENANT_EMAIL_DOMAIN
        email_lower = value.lower()

        if not email_lower.endswith(f'@{domain}'):
            raise serializers.ValidationError(
                f'Only @{domain} email addresses are accepted.'
            )

        if User.objects.filter(email__iexact=email_lower).exists():
            raise serializers.ValidationError('An account with this email already exists.')

        return email_lower

    def validate(self, attrs: dict) -> dict:
        """Validates password match and strength."""
        if attrs['password'] != attrs.pop('password_confirm'):
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})

        validate_password(attrs['password'])
        return attrs

    def create(self, validated_data: dict) -> User:
        """Creates user with hashed password. New accounts start as unverified students."""
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            cu_id=validated_data.get('cu_id', ''),
            department=validated_data.get('department', ''),
            password=validated_data['password'],
            role=User.Role.STUDENT,
            # Auto-verify since we already validated the email domain
            is_verified=True,
        )
        logger.info('New user registered: %s (email: %s)', user.username, user.email)
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Read-only user profile returned after login and in /me/ endpoint.
    Exposes enough data for the Flutter app to render the correct UI by role.
    """

    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'display_name',
            'role',
            'department',
            'cu_id',
            'is_verified',
            'created_at',
        ]
        read_only_fields = fields

    def get_display_name(self, obj: User) -> str:
        return obj.get_display_name()


class FCMTokenUpdateSerializer(serializers.ModelSerializer):
    """
    Updates the FCM device token for the authenticated user.

    Flutter calls PATCH /api/v1/accounts/device/ on every app launch
    to ensure the stored token is always current. FCM tokens can change
    when the app is reinstalled or when Firebase rotates them.
    """

    class Meta:
        model = User
        fields = ['fcm_token']

    def validate_fcm_token(self, value: str) -> str:
        """FCM tokens are non-empty strings. Reject empty updates."""
        if not value or not value.strip():
            raise serializers.ValidationError('FCM token must not be empty.')
        return value.strip()


class PasswordChangeSerializer(serializers.Serializer):
    """
    Allows an authenticated user to change their own password.
    Requires the current password for confirmation before accepting the new one.
    """

    current_password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    new_password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    new_password_confirm = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate_current_password(self, value: str) -> str:
        """Verifies the supplied current password against the stored hash."""
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError(
                {'new_password_confirm': 'New passwords do not match.'}
            )
        validate_password(attrs['new_password'], user=self.context['request'].user)
        return attrs

    def save(self, **kwargs) -> None:
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password', 'updated_at'])
        logger.info('Password changed for user: %s', user.username)
    

