# campusalert/alerts/forms.py

"""
Admin forms for the Alert model.

AdminAlertCreationForm — used exclusively in Django admin for composing alerts.
                         On clean() it runs the classification pipeline and
                         attaches the result to the form so save_model()
                         can persist the classified fields without running
                         the pipeline a second time.
"""

import logging

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Alert

logger = logging.getLogger("campusalert.alerts")


class AdminAlertCreationForm(forms.ModelForm):
    """
    Form for composing a new alert from the Django admin interface.

    Exposes only the fields an administrator should manually provide:
    title, body, category, and dispatch_immediately.

    Classification fields (urgency, classification_method,
    classification_confidence) are intentionally excluded — they are
    populated by the classification pipeline inside clean() and written
    to the instance by AlertAdmin.save_model().

    The optional dispatch_immediately checkbox controls whether the alert
    is enqueued for delivery after being saved (default True). Setting it
    to False saves a CLASSIFIED alert without dispatching — useful for
    drafting and reviewing before release.
    """

    dispatch_immediately = forms.BooleanField(
        required=False,
        initial=True,
        label=_("Dispatch immediately after saving"),
        help_text=_(
            "When checked, the alert is enqueued for FCM and LAN WebSocket delivery "
            "immediately after it is saved. Uncheck to save as CLASSIFIED without dispatching."
        ),
    )

    class Meta:
        model = Alert
        fields = ("title", "body", "category")
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "vTextField",
                    "placeholder": "Short alert title (shown in notification header)",
                    "autofocus": True,
                }
            ),
            "body": forms.Textarea(
                attrs={
                    "class": "vLargeTextField",
                    "rows": 6,
                    "placeholder": "Full alert message body displayed when the user opens the alert.",
                }
            ),
        }
        labels = {
            "title": _("Alert title"),
            "body": _("Message body"),
            "category": _("Category"),
        }
        help_texts = {
            "title": _("Keep this under 80 characters — it appears in the push notification header."),
            "body": _(
                "Full message shown when the recipient opens the alert. "
                "Urgency will be classified automatically from this text."
            ),
            "category": _("Broad topic area. Used for filtering and future routing rules."),
        }

    def clean(self):
        """
        Run the two-stage classification pipeline after field-level validation.

        Attaches the ClassificationResult to self._classification_result so
        AlertAdmin.save_model() can persist it without re-running inference.
        Raises ValidationError if classification fails critically.
        """
        cleaned_data = super().clean()

        title = cleaned_data.get("title", "")
        body = cleaned_data.get("body", "")

        if not title or not body:
            # Individual field errors are already raised — don't double-classify
            return cleaned_data

        try:
            from alerts.services.classifier import classify_alert
            result = classify_alert(title=title, body=body)
            self._classification_result = result

            logger.info(
                "Admin form classified alert: urgency=%s method=%s confidence=%s",
                result.urgency,
                result.method,
                result.confidence,
            )

        except Exception as exc:
            logger.error(
                "Classification pipeline failed during admin form validation: %s",
                exc,
                exc_info=True,
            )
            raise forms.ValidationError(
                _(
                    "The classification pipeline encountered an error. "
                    "Please try again. If the problem persists, contact the system administrator."
                )
            )

        return cleaned_data

    def get_classification_preview(self) -> dict:
        """
        Returns a preview dict of the classification result after clean() has run.
        Used by AlertAdmin.save_model() to read the result without re-running inference.

        Returns:
            dict with keys: urgency, method, confidence — or empty dict if not yet classified.
        """
        result = getattr(self, "_classification_result", None)
        if result is None:
            return {}
        return {
            "urgency": result.urgency,
            "method": result.method,
            "confidence": result.confidence,
        }
    
