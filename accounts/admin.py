# campusalert/accounts/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Admin configuration for the CampusAlert User model.

    Extends Django's built-in UserAdmin to expose CampusAlert-specific fields
    (role, FCM token, verification status, CU ID, department).
    """

    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_verified', 'is_active')
    list_filter = ('role', 'is_verified', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'cu_id')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'last_login', 'date_joined')

    fieldsets = BaseUserAdmin.fieldsets + (
        ('CampusAlert', {
            'fields': ('role', 'cu_id', 'department', 'fcm_token', 'is_verified'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('CampusAlert', {
            'fields': ('email', 'first_name', 'last_name', 'role', 'cu_id', 'department', 'is_verified'),
        }),
    )


