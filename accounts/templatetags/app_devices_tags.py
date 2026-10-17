"""Карточка «Устройства приложения» (вход в GripLine SetupKart аккаунтом сайта, 17.10.2026).

Показывается, только если пользователь вошёл в приложение хотя бы на одном устройстве.
"""
from django import template

register = template.Library()


@register.inclusion_tag('accounts/_app_devices_card.html', takes_context=True)
def app_devices_card(context, card_class='profile-card'):
    from website.setupkart.auth import devices_for
    user = context['request'].user
    devices = list(devices_for(user)) if user.is_authenticated else []
    return {'devices': devices, 'card_class': card_class, 'csrf_token': context.get('csrf_token')}
