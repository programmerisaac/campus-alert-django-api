# core/models.py
"""
Abstract base models for the banking application.

All concrete models across every app inherit from TimeStampedModel,
which provides UUID7 primary keys, automatic timestamps, and client IP capture.
"""

import uuid6
from django.db import models
from django.db.models import F
from django.utils import timezone


class TimeStampedModel(models.Model):
    """
    Abstract base model providing:
    - UUID7 primary key (time-sortable, globally unique, prevents ID guessing)
    - Automatic created_at / updated_at timestamps
    - Python-level age_in_days property for convenience
    - Queryset annotation helper for database-level age calculations
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid6.uuid7,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    @property
    def age_in_days(self) -> int:
        """
        Return the number of days since this record was created.

        Computed in Python — use the queryset annotation method
        annotate_age_in_days() when you need to filter or order by age
        at the database level.
        """
        if self.created_at is None:
            return 0
        delta = timezone.now() - self.created_at
        return delta.days

    @classmethod
    def annotate_age_in_days(cls, queryset):
        """
        Annotate a queryset with 'age_in_days' computed by PostgreSQL.

        Usage:
            qs = MyModel.annotate_age_in_days(MyModel.objects.all())
            qs.filter(age_in_days__gte=30)  # Records older than 30 days

        This pushes the calculation to the database so it can be used
        in .filter(), .order_by(), and .values() without Python overhead.
        """
        from django.db.models import IntegerField
        from django.db.models.functions import Extract, Now

        return queryset.annotate(
            age_in_days=Extract(
                Now() - models.F("created_at"),
                "day",
                output_field=IntegerField(),
            )
        )
    



class SoftDeleteManager(models.Manager):
    """Manager that excludes soft-deleted records by default."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def all_with_deleted(self):
        """Return all records including soft-deleted ones."""
        return super().get_queryset()

    def deleted_only(self):
        """Return only soft-deleted records."""
        return super().get_queryset().filter(is_deleted=True)


class SoftDeleteModel(models.Model):
    """Abstract model with soft delete functionality."""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self):
        """Mark record as deleted without removing from the database."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    def restore(self):
        """Restore a soft-deleted record."""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])




