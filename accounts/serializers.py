# campusalert/accounts/serializers.py
"""
Serializers for the accounts app.

Changes from original:
- validate_email now checks BOTH allowed domains (staff + student)
- Auto-detects role from email domain during registration
- LoginSerializer now accepts email instead of username
- All references to COVENANT_EMAIL_DOMAIN replaced with the new domain list
"""

import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()
logger = logging.getLogger('campusalert.accounts')


def get_domain_from_email(email: str) -> str:
    """
    Extracts the domain part from an email address.

    Example:
        'student@stu.cu.edu.ng' → 'stu.cu.edu.ng'
        'staff@covenantuniversity.edu.ng' → 'covenantuniversity.edu.ng'
    """
    return email.lower().split('@')[-1]


def detect_role_from_email(email: str) -> str:
    """
    Determines the user role based on the email domain.

    Domain mapping:
        @stu.cu.edu.ng              → student
        @covenantuniversity.edu.ng  → staff

    Admins are manually assigned by a superuser after registration.
    They start as staff and get promoted via the Django admin panel.

    Args:
        email: A validated Covenant University email address

    Returns:
        'student' or 'staff' as a string matching User.Role choices
    """
    domain = get_domain_from_email(email)

    if domain == settings.COVENANT_STUDENT_EMAIL_DOMAIN:
        return User.Role.STUDENT
    elif domain == settings.COVENANT_STAFF_EMAIL_DOMAIN:
        return User.Role.STAFF

    # Fallback — should never reach here if validate_email ran first
    return User.Role.STUDENT


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Handles new user registration.

    Enforces:
    - Covenant University email domain (both staff and student domains)
    - Password confirmation and strength validation
    - Auto-detects role from email domain (student vs staff)
    - Admins must be manually assigned by a superuser after registration
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
            # Role is auto-detected from email domain — users cannot self-assign
            'role': {'read_only': True},
        }

    def validate_email(self, value: str) -> str:
        """
        Validates that the email belongs to one of the two allowed
        Covenant University domains.

        Accepted domains:
            @covenantuniversity.edu.ng  (staff)
            @stu.cu.edu.ng              (students)

        This is the primary access control gate — anyone without a
        Covenant University email cannot create an account.
        """
        email_lower = value.lower().strip()
        domain = get_domain_from_email(email_lower)
        allowed_domains = settings.COVENANT_ALLOWED_EMAIL_DOMAINS

        if domain not in allowed_domains:
            # Build a readable list for the error message
            domain_list = ' or '.join(f'@{d}' for d in allowed_domains)
            raise serializers.ValidationError(
                f'Only {domain_list} email addresses are accepted.'
            )

        if User.objects.filter(email__iexact=email_lower).exists():
            raise serializers.ValidationError(
                'An account with this email already exists.'
            )

        return email_lower

    def validate(self, attrs: dict) -> dict:
        """Validates password match and strength."""
        if attrs['password'] != attrs.pop('password_confirm'):
            raise serializers.ValidationError(
                {'password_confirm': 'Passwords do not match.'}
            )
        validate_password(attrs['password'])
        return attrs

    def create(self, validated_data: dict) -> User:
        """
        Creates the user with:
        - Hashed password
        - Role auto-detected from email domain
        - Account auto-verified (email domain already proves identity)
        """
        email = validated_data['email']

        # Auto-detect role from email domain
        role = detect_role_from_email(email)

        user = User.objects.create_user(
            username=validated_data['username'],
            email=email,
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            cu_id=validated_data.get('cu_id', ''),
            department=validated_data.get('department', ''),
            password=validated_data['password'],
            role=role,
            # Auto-verify: email domain validation already confirms identity
            is_verified=True,
        )

        logger.info(
            'New user registered: %s (email: %s, role: %s)',
            user.username,
            user.email,
            user.role,
        )
        return user


class EmailLoginSerializer(serializers.Serializer):
    """
    Validates email + password credentials for the login endpoint.

    This replaces simplejwt's default TokenObtainPairSerializer which
    expects a username field. We accept email instead.

    Validation flow:
    1. Check email and password are present
    2. Call authenticate() which runs our EmailAuthBackend
    3. Check the account is verified (is_verified flag)
    4. Return the authenticated user object

    The view then generates JWT tokens from the returned user.
    """

    email = serializers.EmailField(
        required=True,
        help_text='Your Covenant University email address',
    )
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        help_text='Your account password',
    )

    def validate(self, attrs: dict) -> dict:
        """
        Authenticates the credentials and returns the user.

        Note: authenticate() is called with username=email because Django's
        authentication system always passes the login field as 'username'
        regardless of what it actually is. Our EmailAuthBackend handles this.
        """
        email = attrs.get('email', '').lower().strip()
        password = attrs.get('password', '')

        # authenticate() calls our EmailAuthBackend first
        # Returns None if credentials are wrong OR account is locked by axes
        user = authenticate(
            request=self.context.get('request'),
            username=email,   # EmailAuthBackend receives this as the email
            password=password,
        )

        if user is None:
            raise serializers.ValidationError(
                'Invalid email or password. Please try again.',
                code='authentication_failed',
            )

        # Extra check: only verified accounts can log in
        # (Domain validation during registration auto-verifies, but admins
        # can manually mark accounts as unverified if needed)
        if not user.is_verified:
            raise serializers.ValidationError(
                'Your account is pending verification. '
                'Please contact the university IT helpdesk.',
                code='not_verified',
            )

        # Store user on attrs so the view can access it without another DB query
        attrs['user'] = user
        return attrs


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Read-only user profile returned after login and from the /me/ endpoint.

    Exposes enough data for the React Native app to:
    - Show the correct navigator (student vs admin)
    - Display profile info on the Settings screen
    - Show the user's name in alert feeds
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
    Updates the FCM device push token for the authenticated user.

    The React Native app calls POST /api/v1/accounts/device/ on every
    app launch. FCM tokens can be rotated by Firebase at any time, so
    keeping the stored token fresh is critical for reliable delivery.
    """

    class Meta:
        model = User
        fields = ['fcm_token']

    def validate_fcm_token(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError('FCM token must not be empty.')
        return value.strip()


class PasswordChangeSerializer(serializers.Serializer):
    """
    Allows an authenticated user to change their own password.
    Requires the current password for verification before accepting the new one.
    """

    current_password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )
    new_password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )
    new_password_confirm = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )

    def validate_current_password(self, value: str) -> str:
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
        logger.info('Password changed for user: %s', user.email)


