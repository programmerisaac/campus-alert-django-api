# accounts/backends.py
"""
Custom authentication backend for CampusAlert.

Django's default ModelBackend authenticates using the USERNAME_FIELD,
which is 'username' on the standard User model.

Since CampusAlert uses email + password login (per the PRD), we need
a custom backend that:
  1. Looks up the user by email address (case-insensitive)
  2. Verifies the password
  3. Returns the user object if valid, None otherwise

Django's authentication system tries each backend in AUTHENTICATION_BACKENDS
in order. If a backend returns None, Django tries the next one.
We place this BEFORE the default ModelBackend so email login takes priority.

django-axes integrates with this by wrapping authenticate() — it intercepts
failed attempts and locks the account after AXES_FAILURE_LIMIT failures.
"""

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

User = get_user_model()
logger = logging.getLogger('campusalert.accounts')


class EmailAuthBackend(ModelBackend):
    """
    Authenticates a user using their email address and password.

    Inherits from ModelBackend so all the standard checks apply:
    - is_active check (inactive users cannot log in)
    - has_perm() and has_module_perms() work normally
    - All permission checks remain intact

    Usage:
        Add 'accounts.backends.EmailAuthBackend' to AUTHENTICATION_BACKENDS
        in settings.py, BEFORE 'django.contrib.auth.backends.ModelBackend'.
    """

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,  # Django passes the login field as 'username'
        password: str | None = None,
        **kwargs,
    ) -> User | None:
        """
        Attempt to authenticate using email + password.

        Django's authenticate() always passes the login credential as the
        'username' keyword argument, regardless of what the field actually is.
        We treat this value as an email address.

        Returns the User object on success, None on failure.
        Never raises an exception — returning None signals auth failure.

        Args:
            request:  The HTTP request object (may be None in tests)
            username: Treated as the email address here (Django convention)
            password: The plaintext password to verify
            **kwargs: Additional keyword arguments (ignored)
        """
        if not username or not password:
            # Missing credentials — fail immediately without a DB query
            return None

        try:
            # Case-insensitive email lookup
            # iexact ensures "Student@STU.CU.EDU.NG" matches "student@stu.cu.edu.ng"
            user = User.objects.get(email__iexact=username.strip())

        except User.DoesNotExist:
            # Run the password hasher anyway to prevent timing attacks.
            # Without this, an attacker could detect non-existent accounts
            # by measuring how quickly the response arrives.
            User().set_password(password)
            logger.debug(
                '[EmailAuthBackend] Login attempt for unknown email: %s',
                username,
            )
            return None

        except User.MultipleObjectsReturned:
            # Should never happen — email has a unique constraint.
            # Logged as an error so we can investigate data integrity issues.
            logger.error(
                '[EmailAuthBackend] Multiple users found for email: %s',
                username,
            )
            return None

        # Verify password and run the standard ModelBackend checks
        # (is_active, can_authenticate, etc.)
        if self.user_can_authenticate(user) and user.check_password(password):
            logger.info(
                '[EmailAuthBackend] Successful login for: %s (role: %s)',
                user.email,
                user.role,
            )
            return user

        logger.warning(
            '[EmailAuthBackend] Failed login attempt for: %s',
            user.email,
        )
        return None



