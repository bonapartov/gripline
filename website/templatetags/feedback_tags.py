"""Кнопка «Сообщить об ошибке» — deep link в бота обратной связи.

{% feedback_link 'stage' page %}   — этап (EventPage), 'pilot' driver, 'track' track
{% feedback_link '' %}             — без объекта (страница рейтинга)

Не выводится, если бот выключен, не задан юзернейм или нет активной
категории с нужным кодом.
"""
from django import template
from django.core.cache import cache
from django.utils.html import format_html

from website.feedback import sources

register = template.Library()

CACHE_KEY = 'feedback_link_config_v1'
CACHE_TTL = 60  # сек; плюс страницы кэширует wagtailcache — настройки подхватятся при его очистке


def _config():
    """(username, {код категории}) или None, если кнопку показывать нельзя."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached or None
    from website.models import FeedbackBotSettings, FeedbackCategory
    cfg = FeedbackBotSettings.get()
    if not cfg.is_enabled or not cfg.bot_username.strip():
        value = ()
    else:
        codes = set(FeedbackCategory.objects.filter(is_active=True).exclude(deep_link_code='')
                    .values_list('deep_link_code', flat=True))
        value = (cfg.bot_username.strip().lstrip('@'), codes)
    cache.set(CACHE_KEY, value, CACHE_TTL)
    return value or None


@register.simple_tag
def feedback_link(kind='', obj=None, category='err', css='btn btn-outline-secondary btn-sm',
                  label='Сообщить об ошибке'):
    cfg = _config()
    if not cfg:
        return ''
    username, codes = cfg
    if category not in codes:
        return ''
    if kind and obj is not None and getattr(obj, 'pk', None):
        letter = sources.KIND_TO_LETTER.get(kind)
        if not letter:
            return ''
        url = sources.build_deep_link(username, category, letter, obj.pk)
    else:
        url = f'https://t.me/{username}?start={category}'
    return format_html(
        '<a href="{}" class="{}" target="_blank" rel="noopener nofollow">'
        '<i class="fas fa-bug me-1"></i>{}</a>',
        url, css, label,
    )
