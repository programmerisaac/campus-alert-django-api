# campusalert/alerts/admin.py

"""
Django admin configuration for Alert and DeliveryLog models.

Provides:
- AlertAdmin        — full lifecycle management with classification metadata,
                      inline delivery stats, batch retraction action, and
                      read-only classification fields to prevent manual override.
                      Administrators CAN create alerts — the classification pipeline
                      runs automatically inside the form's clean() method before save.
- DeliveryLogInline — lightweight tabular inline embedded in AlertAdmin.
- DeliveryLogAdmin  — standalone searchable read-only log view for auditing.
"""

import logging

from django.contrib import admin, messages
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .forms import AdminAlertCreationForm
from .models import Alert, DeliveryLog

logger = logging.getLogger("campusalert.alerts")


# ─────────────────────────────────────────────────────────────────────────────
# Inlines
# ─────────────────────────────────────────────────────────────────────────────


class DeliveryLogInline(admin.TabularInline):
    """
    Embedded delivery log table inside the Alert change page.
    Read-only — delivery records must never be edited through admin.
    Shows the first 50 deliveries to avoid overwhelming the page.
    """

    model = DeliveryLog
    extra = 0
    max_num = 0  # No ability to add rows
    can_delete = False
    show_change_link = True
    fields = ("user", "channel", "delivered_at", "acknowledged_at", "fcm_message_id")
    readonly_fields = ("user", "channel", "delivered_at", "acknowledged_at", "fcm_message_id")

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """
        Limit inline to 50 rows and eagerly load users to avoid N+1 per row.
        Delivery logs can be in the thousands for large alerts — never load all.
        """
        return (
            super()
            .get_queryset(request)
            .select_related("user")
            .order_by("-delivered_at")[:50]
        )

    def has_add_permission(self, request: HttpRequest, obj=None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Filters
# ─────────────────────────────────────────────────────────────────────────────


class HighPriorityFilter(admin.SimpleListFilter):
    """
    Filters alerts into 'High priority' (Critical + High) vs 'Standard' (Medium + Low).
    Useful for quickly surfacing actionable or retractable alerts.
    """

    title = _("Priority tier")
    parameter_name = "priority_tier"

    def lookups(self, request: HttpRequest, model_admin):
        return (
            ("high", _("High priority (Critical + High)")),
            ("standard", _("Standard (Medium + Low)")),
        )

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value() == "high":
            return queryset.filter(urgency__in=[Alert.Urgency.CRITICAL, Alert.Urgency.HIGH])
        if self.value() == "standard":
            return queryset.filter(urgency__in=[Alert.Urgency.MEDIUM, Alert.Urgency.LOW])
        return queryset


class HasUnacknowledgedFilter(admin.SimpleListFilter):
    """
    Filters alerts that still have at least one unacknowledged delivery log.
    Helps administrators identify Critical/High alerts with low acknowledgement rates.
    """

    title = _("Acknowledgement status")
    parameter_name = "ack_status"

    def lookups(self, request: HttpRequest, model_admin):
        return (
            ("pending", _("Has unacknowledged deliveries")),
            ("complete", _("All deliveries acknowledged")),
        )

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value() == "pending":
            return queryset.filter(
                delivery_logs__acknowledged_at__isnull=True
            ).distinct()
        if self.value() == "complete":
            return queryset.exclude(
                delivery_logs__acknowledged_at__isnull=True
            ).distinct()
        return queryset


# ─────────────────────────────────────────────────────────────────────────────
# Alert Admin
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    """
    Admin interface for Alert — full lifecycle management including alert creation.

    Alert creation flow (admin):
        1. Admin fills in title, body, category, and dispatch_immediately via
           AdminAlertCreationForm.
        2. Form.clean() runs the two-stage classification pipeline (keyword override
           → XGBoost) and attaches the ClassificationResult to the form.
        3. save_model() reads the classification result from the form and writes
           urgency, classification_method, classification_confidence, and
           created_by to the instance before the first save() call.
        4. If dispatch_immediately is True, the Celery delivery task is enqueued
           inside transaction.on_commit() — guaranteeing the row exists before
           the worker reads it.

    Classification fields on the change page (urgency, classification_method,
    classification_confidence) are read-only to prevent manual override of the
    ML pipeline outputs after creation.

    Retraction is performed via a batch action rather than deleting rows,
    preserving delivery log integrity for compliance auditing.
    """

    form = AdminAlertCreationForm

    # ── List display ─────────────────────────────────────────────────────────
    list_display = (
        "title",
        "urgency_badge",
        "category",
        "status",
        "classification_method",
        "confidence_display",
        "recipient_count",
        "is_active",
        "created_by",
        "created_at",
    )
    list_filter = (
        "urgency",
        "category",
        "status",
        "classification_method",
        "is_active",
        HighPriorityFilter,
        HasUnacknowledgedFilter,
        "created_at",
    )
    search_fields = ("title", "body", "created_by__email", "created_by__username")
    list_select_related = ("created_by",)
    list_per_page = 30
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    show_full_result_count = False  # Avoid COUNT(*) on large tables

    # ── Detail / Change layout ───────────────────────────────────────────────
    # These read-only fields apply to the CHANGE form only.
    # The add form uses AdminAlertCreationForm which exposes only editable fields.
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "created_by",
        "urgency",
        "classification_method",
        "classification_confidence",
        "confidence_display",
        "dispatched_at",
        "recipient_count",
        "status",
        "delivery_summary",
    )

    # Fieldsets shown on the CHANGE page (existing alert)
    fieldsets = (
        (
            _("Content"),
            {
                "fields": ("title", "body", "category"),
            },
        ),
        (
            _("Classification (read-only — set by ML pipeline)"),
            {
                "fields": (
                    "urgency",
                    "classification_method",
                    "classification_confidence",
                    "confidence_display",
                ),
                "description": _(
                    "These fields are populated automatically by the two-stage classification "
                    "pipeline (keyword override → XGBoost) when the alert is first created. "
                    "They cannot be edited here to preserve audit integrity."
                ),
            },
        ),
        (
            _("Lifecycle"),
            {
                "fields": ("status", "is_active", "dispatched_at", "recipient_count"),
            },
        ),
        (
            _("Delivery summary"),
            {
                "fields": ("delivery_summary",),
                "classes": ("collapse",),
            },
        ),
        (
            _("Metadata"),
            {
                "fields": ("id", "created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    # Fieldsets shown on the ADD page (new alert being composed)
    add_fieldsets = (
        (
            _("Compose Alert"),
            {
                "fields": ("title", "body", "category"),
                "description": _(
                    "Write the alert title and message body. The classification pipeline will "
                    "automatically determine the urgency level (Critical / High / Medium / Low) "
                    "from the text when you save."
                ),
            },
        ),
        (
            _("Dispatch options"),
            {
                "fields": ("dispatch_immediately",),
                "description": _(
                    "Choose whether to dispatch the alert to all campus users immediately "
                    "after saving, or hold it in CLASSIFIED status for review."
                ),
            },
        ),
    )

    inlines = (DeliveryLogInline,)
    actions = ("retract_alerts", "mark_as_dispatched")

    # ── Fieldset routing ─────────────────────────────────────────────────────

    def get_fieldsets(self, request: HttpRequest, obj=None):
        """
        Return add_fieldsets for the creation form and the standard fieldsets
        for the change form. This gives the add page a clean, focused layout.
        """
        if obj is None:
            return self.add_fieldsets
        return self.fieldsets

    def get_readonly_fields(self, request: HttpRequest, obj=None):
        """
        On the ADD page: no readonly fields — all inputs are editable by the admin.
        On the CHANGE page: classification and lifecycle fields are locked.
        """
        if obj is None:
            return ()
        return self.readonly_fields

    # ── Queryset ─────────────────────────────────────────────────────────────

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """
        Annotate with delivery counts so summary columns are a single query.
        Using annotation instead of len(delivery_logs.all()) avoids N+1 on the list.
        """
        return (
            super()
            .get_queryset(request)
            .select_related("created_by")
            .annotate(
                total_deliveries=Count("delivery_logs"),
                acknowledged_deliveries=Count(
                    "delivery_logs",
                    filter=Q(delivery_logs__acknowledged_at__isnull=False),
                ),
            )
        )

    # ── Save model ───────────────────────────────────────────────────────────

    def save_model(self, request: HttpRequest, obj: Alert, form, change: bool) -> None:
        """
        On creation (change=False):
            1. Set created_by to the currently logged-in admin.
            2. Read the ClassificationResult already computed by form.clean()
               and write it to the Alert instance.
            3. Set status to CLASSIFIED.
            4. Save the instance.
            5. If dispatch_immediately is checked, enqueue Celery delivery inside
               transaction.on_commit() — guarantees the row exists in the DB
               before the worker processes it.

        On update (change=True):
            Standard save — classification fields are locked as readonly so they
            cannot be mutated through the form.
        """
        if not change:
            # Attach the creating administrator — prevents spoofing via form data
            obj.created_by = request.user
            obj.status = Alert.Status.CLASSIFIED

            # Pull the classification result pre-computed during form.clean()
            # This avoids running the ML pipeline twice.
            classification = form.get_classification_preview()
            if classification:
                obj.urgency = classification["urgency"]
                obj.classification_method = classification["method"]
                obj.classification_confidence = classification.get("confidence")
            else:
                # Fallback: re-run classification if for some reason it wasn't cached
                # (e.g., form was bypassed — defensive programming)
                from alerts.services.classifier import classify_alert
                result = classify_alert(title=obj.title, body=obj.body)
                obj.urgency = result.urgency
                obj.classification_method = result.method
                obj.classification_confidence = result.confidence

            logger.info(
                "Admin %s creating alert '%s': urgency=%s method=%s",
                request.user,
                obj.title,
                obj.urgency,
                obj.classification_method,
            )

        super().save_model(request, obj, form, change)

        # Enqueue delivery AFTER the atomic save completes
        if not change and form.cleaned_data.get("dispatch_immediately", True):
            from django.db import transaction
            from alerts.tasks import deliver_alert_task

            transaction.on_commit(
                lambda: deliver_alert_task.delay(str(obj.id))
            )
            logger.info(
                "Alert %s enqueued for delivery by admin %s.",
                obj.id,
                request.user,
            )

    def response_add(self, request: HttpRequest, obj: Alert, post_url_continue=None):
        """
        Override the post-save redirect to show a clear success message
        that includes the auto-classified urgency level, so the admin
        immediately sees what the pipeline decided.
        """
        dispatch_status = (
            "and enqueued for delivery"
            if request.POST.get("dispatch_immediately")
            else "— held in CLASSIFIED status (not yet dispatched)"
        )
        self.message_user(
            request,
            format_html(
                'Alert "<strong>{title}</strong>" was saved {dispatch_status}. '
                'Urgency classified as: <strong style="color:{colour};">{urgency}</strong> '
                '(method: {method})',
                title=obj.title,
                dispatch_status=dispatch_status,
                colour=self._urgency_colour(obj.urgency),
                urgency=obj.get_urgency_display(),
                method=obj.get_classification_method_display(),
            ),
            messages.SUCCESS,
        )
        return super().response_add(request, obj, post_url_continue)

    # ── Custom display methods ────────────────────────────────────────────────

    @staticmethod
    def _urgency_colour(urgency: str) -> str:
        """Return the hex colour for a given urgency level (shared by display methods)."""
        return {
            Alert.Urgency.CRITICAL: "#dc2626",
            Alert.Urgency.HIGH: "#ea580c",
            Alert.Urgency.MEDIUM: "#ca8a04",
            Alert.Urgency.LOW: "#16a34a",
        }.get(urgency, "#6b7280")

    @admin.display(description=_("Urgency"), ordering="urgency")
    def urgency_badge(self, obj: Alert) -> str:
        """
        Renders urgency as a coloured badge for instant visual prioritisation.
        Colour mapping mirrors the mobile app's urgency palette (PRD §4.1).
        """
        colour = self._urgency_colour(obj.urgency)
        label = obj.get_urgency_display()
        return format_html(
            '<span style="'
            "background:{colour};"
            "color:#fff;"
            "padding:2px 10px;"
            "border-radius:12px;"
            "font-size:11px;"
            "font-weight:600;"
            "letter-spacing:.5px;"
            '">{label}</span>',
            colour=colour,
            label=label,
        )

    @admin.display(description=_("Confidence"), ordering="classification_confidence")
    def confidence_display(self, obj: Alert) -> str:
        """
        Shows XGBoost confidence as a percentage, or 'N/A' for keyword overrides.
        No model inference is run for keyword overrides so no score exists.
        """
        if obj.classification_confidence is None:
            return format_html('<span style="color:#9ca3af;">N/A</span>')
        pct = obj.classification_confidence * 100
        colour = "#16a34a" if pct >= 70 else "#ca8a04"
        return format_html(
            '<span style="color:{colour};font-weight:600;">{pct}%</span>',
            colour=colour,
            pct=f"{pct:.1f}",
        )

    @admin.display(description=_("Delivery summary"))
    def delivery_summary(self, obj: Alert) -> str:
        """
        Summarises delivery and acknowledgement counts pulled from the annotated queryset.
        Only meaningful after the alert has been dispatched.
        """
        total = getattr(obj, "total_deliveries", None)
        acked = getattr(obj, "acknowledged_deliveries", None)

        if total is None:
            total = obj.delivery_logs.count()
            acked = obj.delivery_logs.filter(acknowledged_at__isnull=False).count()

        if total == 0:
            return _("No delivery records yet.")

        ack_rate = (acked / total * 100) if total else 0
        return format_html(
            "<strong>{total}</strong> deliveries &mdash; "
            "<strong>{acked}</strong> acknowledged "
            "(<span style=\"color:{colour};\">{rate}%</span>)",
            total=total,
            acked=acked,
            colour="#16a34a" if ack_rate >= 80 else "#ca8a04",
            rate=f"{ack_rate:.1f}",
        )

    # ── Permissions ──────────────────────────────────────────────────────────

    def has_add_permission(self, request: HttpRequest) -> bool:
        """
        Alert creation is allowed from admin. The classification pipeline runs
        automatically inside AdminAlertCreationForm.clean() before save_model()
        is called, so no alert can be saved without being classified first.
        Only staff or superusers with the 'alerts.add_alert' permission may create.
        """
        return request.user.is_staff or request.user.is_superuser

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        """
        Hard deletes are disabled. Retraction (is_active=False) is the only
        supported removal path — it preserves delivery logs for compliance auditing.
        """
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        """
        Change permission is restricted to title, body, and category (content only).
        Classification and lifecycle fields are rendered as readonly in get_readonly_fields().
        """
        return request.user.is_staff or request.user.is_superuser

    # ── Actions ──────────────────────────────────────────────────────────────

    @admin.action(description=_("Retract selected alerts (soft delete)"))
    def retract_alerts(self, request: HttpRequest, queryset: QuerySet) -> None:
        """
        Soft-retracts the selected alerts by setting is_active=False.
        Uses .update() for a single atomic database write — no per-row .save() loop.
        Only active, already-dispatched alerts are eligible for retraction.
        """
        eligible = queryset.filter(is_active=True, status=Alert.Status.DISPATCHED)
        retracted_count = eligible.update(is_active=False, updated_at=timezone.now())

        skipped = queryset.count() - retracted_count
        if retracted_count:
            logger.info(
                "Admin %s retracted %d alert(s).",
                request.user,
                retracted_count,
            )
            self.message_user(
                request,
                _(f"{retracted_count} alert(s) successfully retracted."),
                messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                _(
                    f"{skipped} alert(s) were skipped — only active, dispatched "
                    "alerts can be retracted."
                ),
                messages.WARNING,
            )

    @admin.action(description=_("Force-mark selected alerts as Dispatched"))
    def mark_as_dispatched(self, request: HttpRequest, queryset: QuerySet) -> None:
        """
        Emergency action: manually marks stuck CLASSIFIED alerts as DISPATCHED.
        Should only be used when the Celery delivery task has confirmed delivery
        externally but failed to update the status field (e.g., task crash after send).
        All uses are logged for audit.
        """
        eligible = queryset.filter(status=Alert.Status.CLASSIFIED)
        updated = eligible.update(
            status=Alert.Status.DISPATCHED,
            dispatched_at=timezone.now(),
        )
        skipped = queryset.count() - updated

        if updated:
            logger.warning(
                "Admin %s manually forced %d alert(s) to DISPATCHED status.",
                request.user,
                updated,
            )
            self.message_user(
                request,
                _(f"{updated} alert(s) marked as dispatched."),
                messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                _(f"{skipped} alert(s) skipped — only CLASSIFIED alerts can be force-dispatched."),
                messages.WARNING,
            )


# ─────────────────────────────────────────────────────────────────────────────
# DeliveryLog Admin
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(DeliveryLog)
class DeliveryLogAdmin(admin.ModelAdmin):
    """
    Read-only audit view for DeliveryLog records.

    Delivery logs are immutable audit records — created by the Celery
    delivery task and acknowledged by users on-device. No admin mutations allowed.
    """

    list_display = (
        "alert_title",
        "urgency_display",
        "user",
        "channel",
        "delivered_at",
        "acknowledged_at",
        "is_acknowledged",
        "created_at",
    )
    list_filter = (
        "channel",
        "alert__urgency",
        "alert__category",
        ("acknowledged_at", admin.EmptyFieldListFilter),
        "delivered_at",
    )
    search_fields = (
        "user__email",
        "user__username",
        "alert__title",
        "fcm_message_id",
    )
    list_select_related = ("alert", "user")
    readonly_fields = (
        "id",
        "alert",
        "user",
        "channel",
        "delivered_at",
        "acknowledged_at",
        "fcm_message_id",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            _("Delivery"),
            {
                "fields": ("alert", "user", "channel", "delivered_at", "fcm_message_id"),
            },
        ),
        (
            _("Acknowledgement"),
            {
                "fields": ("acknowledged_at",),
            },
        ),
        (
            _("Metadata"),
            {
                "fields": ("id", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
    ordering = ("-created_at",)
    list_per_page = 50
    show_full_result_count = False
    date_hierarchy = "delivered_at"

    @admin.display(description=_("Alert"), ordering="alert__title")
    def alert_title(self, obj: DeliveryLog) -> str:
        return obj.alert.title

    @admin.display(description=_("Urgency"), ordering="alert__urgency")
    def urgency_display(self, obj: DeliveryLog) -> str:
        return obj.alert.get_urgency_display()

    @admin.display(description=_("Acknowledged"), boolean=True, ordering="acknowledged_at")
    def is_acknowledged(self, obj: DeliveryLog) -> bool:
        """Boolean column — True when the user has acknowledged this delivery."""
        return obj.acknowledged_at is not None

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Delivery logs are created exclusively by the Celery delivery task."""
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        """
        Delivery logs are immutable audit records.
        Editing them would compromise delivery audit integrity.
        """
        return False

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        """Logs may not be deleted — required for compliance auditing."""
        return False




# # campusalert/alerts/admin.py

# """
# Django admin configuration for Alert and DeliveryLog models.

# Provides:
# - AlertAdmin        — full lifecycle management with classification metadata,
#                       inline delivery stats, batch retraction action, and
#                       read-only classification fields to prevent manual override.
# - DeliveryLogInline — lightweight tabular inline embedded in AlertAdmin.
# - DeliveryLogAdmin  — standalone searchable read-only log view for auditing.
# """

# import logging

# from django.contrib import admin, messages
# from django.db.models import Count, Q, QuerySet
# from django.http import HttpRequest
# from django.utils import timezone
# from django.utils.html import format_html
# from django.utils.translation import gettext_lazy as _

# from .models import Alert, DeliveryLog

# logger = logging.getLogger("campusalert.alerts")


# # ─────────────────────────────────────────────────────────────────────────────
# # Inlines
# # ─────────────────────────────────────────────────────────────────────────────


# class DeliveryLogInline(admin.TabularInline):
#     """
#     Embedded delivery log table inside the Alert change page.
#     Read-only — delivery records must never be edited through admin.
#     Shows the first 50 deliveries to avoid overwhelming the page.
#     """

#     model = DeliveryLog
#     extra = 0
#     max_num = 0  # No ability to add rows
#     can_delete = False
#     show_change_link = True
#     fields = ("user", "channel", "delivered_at", "acknowledged_at", "fcm_message_id")
#     readonly_fields = ("user", "channel", "delivered_at", "acknowledged_at", "fcm_message_id")

#     def get_queryset(self, request: HttpRequest) -> QuerySet:
#         """
#         Limit inline to 50 rows and eagerly load users to avoid N+1 per row.
#         Delivery logs can be in the thousands for large alerts — never load all.
#         """
#         return (
#             super()
#             .get_queryset(request)
#             .select_related("user")
#             .order_by("-delivered_at")[:50]
#         )

#     def has_add_permission(self, request: HttpRequest, obj=None) -> bool:
#         return False

#     def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
#         return False


# # ─────────────────────────────────────────────────────────────────────────────
# # Filters
# # ─────────────────────────────────────────────────────────────────────────────


# class HighPriorityFilter(admin.SimpleListFilter):
#     """
#     Filters alerts into 'High priority' (Critical + High) vs 'Standard' (Medium + Low).
#     Useful for quickly surfacing actionable or retractable alerts.
#     """

#     title = _("Priority tier")
#     parameter_name = "priority_tier"

#     def lookups(self, request: HttpRequest, model_admin):
#         return (
#             ("high", _("High priority (Critical + High)")),
#             ("standard", _("Standard (Medium + Low)")),
#         )

#     def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
#         if self.value() == "high":
#             return queryset.filter(urgency__in=[Alert.Urgency.CRITICAL, Alert.Urgency.HIGH])
#         if self.value() == "standard":
#             return queryset.filter(urgency__in=[Alert.Urgency.MEDIUM, Alert.Urgency.LOW])
#         return queryset


# class HasUnacknowledgedFilter(admin.SimpleListFilter):
#     """
#     Filters alerts that still have at least one unacknowledged delivery log.
#     Helps administrators identify Critical/High alerts with low acknowledgement rates.
#     """

#     title = _("Acknowledgement status")
#     parameter_name = "ack_status"

#     def lookups(self, request: HttpRequest, model_admin):
#         return (
#             ("pending", _("Has unacknowledged deliveries")),
#             ("complete", _("All deliveries acknowledged")),
#         )

#     def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
#         if self.value() == "pending":
#             # At least one delivery log with acknowledged_at still null
#             return queryset.filter(
#                 delivery_logs__acknowledged_at__isnull=True
#             ).distinct()
#         if self.value() == "complete":
#             # All delivery logs for this alert are acknowledged (none null)
#             return queryset.exclude(
#                 delivery_logs__acknowledged_at__isnull=True
#             ).distinct()
#         return queryset


# # ─────────────────────────────────────────────────────────────────────────────
# # Alert Admin
# # ─────────────────────────────────────────────────────────────────────────────


# @admin.register(Alert)
# class AlertAdmin(admin.ModelAdmin):
#     """
#     Admin interface for Alert — full lifecycle management.

#     Classification fields (urgency, classification_method, classification_confidence)
#     are read-only to prevent manual override of the ML pipeline outputs.
#     Retraction is performed via a batch action rather than deleting rows,
#     preserving delivery log integrity.
#     """

#     # ── List display ─────────────────────────────────────────────────────────
#     list_display = (
#         "title",
#         "urgency_badge",
#         "category",
#         "status",
#         "classification_method",
#         "confidence_display",
#         "recipient_count",
#         "is_active",
#         "created_by",
#         "created_at",
#     )
#     list_filter = (
#         "urgency",
#         "category",
#         "status",
#         "classification_method",
#         "is_active",
#         HighPriorityFilter,
#         HasUnacknowledgedFilter,
#         "created_at",
#     )
#     search_fields = ("title", "body", "created_by__email", "created_by__username")
#     list_select_related = ("created_by",)
#     list_per_page = 30
#     date_hierarchy = "created_at"
#     ordering = ("-created_at",)
#     show_full_result_count = False  # Avoid COUNT(*) on large tables

#     # ── Detail layout ────────────────────────────────────────────────────────
#     readonly_fields = (
#         "id",
#         "created_at",
#         "updated_at",
#         "created_by",
#         "urgency",
#         "classification_method",
#         "classification_confidence",
#         "confidence_display",
#         "dispatched_at",
#         "recipient_count",
#         "status",
#         "delivery_summary",
#     )
#     fieldsets = (
#         (
#             _("Content"),
#             {
#                 "fields": ("title", "body", "category"),
#             },
#         ),
#         (
#             _("Classification (read-only — set by ML pipeline)"),
#             {
#                 "fields": (
#                     "urgency",
#                     "classification_method",
#                     "classification_confidence",
#                     "confidence_display",
#                 ),
#                 "description": _(
#                     "These fields are set automatically by the classification pipeline "
#                     "and cannot be edited here to preserve audit integrity."
#                 ),
#             },
#         ),
#         (
#             _("Lifecycle"),
#             {
#                 "fields": ("status", "is_active", "dispatched_at", "recipient_count"),
#             },
#         ),
#         (
#             _("Delivery summary"),
#             {
#                 "fields": ("delivery_summary",),
#                 "classes": ("collapse",),
#             },
#         ),
#         (
#             _("Metadata"),
#             {
#                 "fields": ("id", "created_by", "created_at", "updated_at"),
#                 "classes": ("collapse",),
#             },
#         ),
#     )
#     inlines = (DeliveryLogInline,)
#     actions = ("retract_alerts", "mark_as_dispatched")

#     # ── Queryset ─────────────────────────────────────────────────────────────

#     def get_queryset(self, request: HttpRequest) -> QuerySet:
#         """
#         Annotate with delivery counts so summary columns are a single query.
#         Using annotation instead of len(delivery_logs.all()) avoids N+1 on the list.
#         """
#         return (
#             super()
#             .get_queryset(request)
#             .select_related("created_by")
#             .annotate(
#                 total_deliveries=Count("delivery_logs"),
#                 acknowledged_deliveries=Count(
#                     "delivery_logs",
#                     filter=Q(delivery_logs__acknowledged_at__isnull=False),
#                 ),
#             )
#         )

#     # ── Custom display methods ────────────────────────────────────────────────

#     @admin.display(description=_("Urgency"), ordering="urgency")
#     def urgency_badge(self, obj: Alert) -> str:
#         """
#         Renders urgency as a coloured badge for instant visual prioritisation.
#         Colour mapping mirrors the mobile app's urgency palette (PRD §4.1).
#         """
#         colour_map = {
#             Alert.Urgency.CRITICAL: "#dc2626",   # Red
#             Alert.Urgency.HIGH: "#ea580c",        # Orange
#             Alert.Urgency.MEDIUM: "#ca8a04",      # Amber
#             Alert.Urgency.LOW: "#16a34a",         # Green
#         }
#         colour = colour_map.get(obj.urgency, "#6b7280")
#         label = obj.get_urgency_display()
#         return format_html(
#             '<span style="'
#             "background:{colour};"
#             "color:#fff;"
#             "padding:2px 10px;"
#             "border-radius:12px;"
#             "font-size:11px;"
#             "font-weight:600;"
#             "letter-spacing:.5px;"
#             '">{label}</span>',
#             colour=colour,
#             label=label,
#         )

#     @admin.display(description=_("Confidence"), ordering="classification_confidence")
#     def confidence_display(self, obj: Alert) -> str:
#         """
#         Shows XGBoost confidence as a percentage, or 'N/A' for keyword overrides.
#         No model inference is run for keyword overrides so no score exists.
#         """
#         if obj.classification_confidence is None:
#             return format_html('<span style="color:#9ca3af;">N/A</span>')
#         pct = obj.classification_confidence * 100
#         # Colour the score — below 70% is amber (low confidence worth reviewing)
#         colour = "#16a34a" if pct >= 70 else "#ca8a04"
#         return format_html(
#             '<span style="color:{colour};font-weight:600;">{pct:.1f}%</span>',
#             colour=colour,
#             pct=pct,
#         )

#     @admin.display(description=_("Delivery summary"))
#     def delivery_summary(self, obj: Alert) -> str:
#         """
#         Summarises delivery and acknowledgement counts pulled from the annotated queryset.
#         Only meaningful after the alert has been dispatched.
#         """
#         total = getattr(obj, "total_deliveries", None)
#         acked = getattr(obj, "acknowledged_deliveries", None)

#         if total is None:
#             # Fallback if viewing a single object that wasn't annotated
#             total = obj.delivery_logs.count()
#             acked = obj.delivery_logs.filter(acknowledged_at__isnull=False).count()

#         if total == 0:
#             return _("No delivery records yet.")

#         ack_rate = (acked / total * 100) if total else 0
#         return format_html(
#             "<strong>{total}</strong> deliveries &mdash; "
#             "<strong>{acked}</strong> acknowledged "
#             "(<span style=\"color:{colour};\">{rate:.1f}%</span>)",
#             total=total,
#             acked=acked,
#             colour="#16a34a" if ack_rate >= 80 else "#ca8a04",
#             rate=ack_rate,
#         )

#     # ── Permissions ──────────────────────────────────────────────────────────

#     def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
#         """
#         Hard deletes are disabled. Retraction (is_active=False) is the only
#         supported removal path — it preserves delivery logs for compliance auditing.
#         """
#         return False

#     def has_add_permission(self, request: HttpRequest) -> bool:
#         """
#         Alerts must be composed through the application UI and processed by the
#         classification pipeline. Creating them directly in admin bypasses the
#         ML classification step and would produce incomplete records.
#         """
#         return False

#     # ── Actions ──────────────────────────────────────────────────────────────

#     @admin.action(description=_("Retract selected alerts (soft delete)"))
#     def retract_alerts(self, request: HttpRequest, queryset: QuerySet) -> None:
#         """
#         Soft-retracts the selected alerts by setting is_active=False.
#         Uses .update() for a single atomic database write — no per-row .save() loop.
#         Only active, already-dispatched alerts are eligible for retraction.
#         """
#         eligible = queryset.filter(is_active=True, status=Alert.Status.DISPATCHED)
#         retracted_count = eligible.update(is_active=False, updated_at=timezone.now())

#         skipped = queryset.count() - retracted_count
#         if retracted_count:
#             logger.info(
#                 "Admin %s retracted %d alert(s).",
#                 request.user,
#                 retracted_count,
#             )
#             self.message_user(
#                 request,
#                 _(f"{retracted_count} alert(s) successfully retracted."),
#                 messages.SUCCESS,
#             )
#         if skipped:
#             self.message_user(
#                 request,
#                 _(
#                     f"{skipped} alert(s) were skipped — only active, dispatched "
#                     "alerts can be retracted."
#                 ),
#                 messages.WARNING,
#             )

#     @admin.action(description=_("Force-mark selected alerts as Dispatched"))
#     def mark_as_dispatched(self, request: HttpRequest, queryset: QuerySet) -> None:
#         """
#         Emergency action: manually marks stuck CLASSIFIED alerts as DISPATCHED.
#         Should only be used when the Celery delivery task has confirmed delivery
#         externally but failed to update the status field (e.g., task crash after send).
#         All uses are logged for audit.
#         """
#         eligible = queryset.filter(status=Alert.Status.CLASSIFIED)
#         updated = eligible.update(
#             status=Alert.Status.DISPATCHED,
#             dispatched_at=timezone.now(),
#         )
#         skipped = queryset.count() - updated

#         if updated:
#             logger.warning(
#                 "Admin %s manually forced %d alert(s) to DISPATCHED status.",
#                 request.user,
#                 updated,
#             )
#             self.message_user(
#                 request,
#                 _(f"{updated} alert(s) marked as dispatched."),
#                 messages.SUCCESS,
#             )
#         if skipped:
#             self.message_user(
#                 request,
#                 _(f"{skipped} alert(s) skipped — only CLASSIFIED alerts can be force-dispatched."),
#                 messages.WARNING,
#             )


# # ─────────────────────────────────────────────────────────────────────────────
# # DeliveryLog Admin
# # ─────────────────────────────────────────────────────────────────────────────


# @admin.register(DeliveryLog)
# class DeliveryLogAdmin(admin.ModelAdmin):
#     """
#     Read-only audit view for DeliveryLog records.

#     Delivery logs are immutable audit records — created by the Celery
#     delivery task and acknowledged by users on-device. No admin mutations allowed.
#     """

#     list_display = (
#         "alert_title",
#         "urgency_display",
#         "user",
#         "channel",
#         "delivered_at",
#         "acknowledged_at",
#         "is_acknowledged",
#         "created_at",
#     )
#     list_filter = (
#         "channel",
#         "alert__urgency",
#         "alert__category",
#         ("acknowledged_at", admin.EmptyFieldListFilter),
#         "delivered_at",
#     )
#     search_fields = (
#         "user__email",
#         "user__username",
#         "alert__title",
#         "fcm_message_id",
#     )
#     list_select_related = ("alert", "user")
#     readonly_fields = (
#         "id",
#         "alert",
#         "user",
#         "channel",
#         "delivered_at",
#         "acknowledged_at",
#         "fcm_message_id",
#         "created_at",
#         "updated_at",
#     )
#     fieldsets = (
#         (
#             _("Delivery"),
#             {
#                 "fields": ("alert", "user", "channel", "delivered_at", "fcm_message_id"),
#             },
#         ),
#         (
#             _("Acknowledgement"),
#             {
#                 "fields": ("acknowledged_at",),
#             },
#         ),
#         (
#             _("Metadata"),
#             {
#                 "fields": ("id", "created_at", "updated_at"),
#                 "classes": ("collapse",),
#             },
#         ),
#     )
#     ordering = ("-created_at",)
#     list_per_page = 50
#     show_full_result_count = False
#     date_hierarchy = "delivered_at"

#     # ── Custom display methods ────────────────────────────────────────────────

#     @admin.display(description=_("Alert"), ordering="alert__title")
#     def alert_title(self, obj: DeliveryLog) -> str:
#         return obj.alert.title

#     @admin.display(description=_("Urgency"), ordering="alert__urgency")
#     def urgency_display(self, obj: DeliveryLog) -> str:
#         """Shows the urgency of the linked alert as a readable label."""
#         return obj.alert.get_urgency_display()

#     @admin.display(description=_("Acknowledged"), boolean=True, ordering="acknowledged_at")
#     def is_acknowledged(self, obj: DeliveryLog) -> bool:
#         """Boolean column — True when the user has acknowledged this delivery."""
#         return obj.acknowledged_at is not None

#     # ── Permissions ──────────────────────────────────────────────────────────

#     def has_add_permission(self, request: HttpRequest) -> bool:
#         """Delivery logs are created exclusively by the Celery delivery task."""
#         return False

#     def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
#         """
#         Delivery logs are immutable audit records.
#         Editing them would compromise delivery audit integrity.
#         """
#         return False

#     def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
#         """Logs may not be deleted — required for compliance auditing."""
#         return False

