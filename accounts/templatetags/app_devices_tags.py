"""Карточка «Приложение GripLine SetupKart» в ЛК (17.10.2026): входы в приложение и сессии из него.

Показывается, только если пользователь входил в приложение или у него есть сессии из приложения
(в ЛК команды — сессии пилотов команды).
"""
from django import template

register = template.Library()


@register.inclusion_tag('accounts/_app_devices_card.html', takes_context=True)
def app_devices_card(context, card_class='profile-card', mode='own'):
    from website.models import AppSyncRecord
    from website.setupkart.auth import devices_for
    from website.setupkart.session_views import team_sessions_qs
    user = context['request'].user
    if not user.is_authenticated:
        return {'devices': [], 'sessions': 0}
    devices = list(devices_for(user))
    if mode == 'team':
        sessions = team_sessions_qs(user).count()
    else:
        sessions = AppSyncRecord.objects.filter(user=user, table='sessions', deleted=False).count()
    return {'devices': devices, 'sessions': sessions, 'mode': mode, 'card_class': card_class,
            'csrf_token': context.get('csrf_token')}
