"""Значок в шапке: сколько документов в ЛК истекло или скоро истечёт (applications/reminders.py)."""
from datetime import timedelta

from django import template
from django.utils import timezone

register = template.Library()


@register.simple_tag
def document_alert_count(user):
    if not getattr(user, 'is_authenticated', False):
        return 0
    try:
        from accounts.models import PilotDocument
        from applications.models import DocumentReminderSettings
        horizon = max(DocumentReminderSettings.get().days() or [30])
        return PilotDocument.objects.filter(
            profile__user=user, expiry_date__lte=timezone.localdate() + timedelta(days=horizon)).count()
    except Exception:
        return 0  # шапка не должна падать из-за значка
