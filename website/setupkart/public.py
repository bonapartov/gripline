"""Тренировки из приложения на публичной странице пилота (17.10.2026, этап 4).

Только сессии, которые пилот сам отметил «На странице», при включённом общем разрешении, и только сохранённые
его собственным аккаунтом (сессии, которые завёл менеджер команды, на страницу пилота не попадают — это решение
пилота). Показываются дата, трасса, класс, лучший круг и число кругов — без настроек карта.
"""
import json

from django.utils import timezone

from website.models import AppSyncRecord

from .session_display import laptime

PUBLIC_LIMIT = 30


def training_sessions(driver):
    records = (AppSyncRecord.objects
               .filter(table='sessions', deleted=False, public=True, driver=driver,
                       user__profile__driver=driver, user__profile__verified=True,
                       user__profile__app_sessions_public=True)
               .select_related('track').order_by('-started_at')[:PUBLIC_LIMIT])
    out = []
    for r in records:
        try:
            setup = json.loads(r.data.get('setupJson') or '{}')
        except (TypeError, ValueError):
            setup = {}
        laps = [x for x in (setup.get('laps') or []) if isinstance(x, (int, float)) and x > 0]
        out.append({
            'date': timezone.localtime(r.started_at) if r.started_at else None,
            'track': r.track.name if r.track else (setup.get('track') or ''),
            'race_class': setup.get('engine_category') or '',
            'best': laptime(r.data.get('bestTimeMs')),
            'laps': len(laps) or '',
        })
    return out


def purge_driver_page(driver):
    """Страница пилота закэширована wagtailcache — после смены видимости сбросить её."""
    if driver is None:
        return
    import re
    from wagtailcache.cache import clear_cache
    # clear_cache принимает регулярные выражения по ключам кэша (полный адрес страницы).
    try:
        clear_cache([r'^https?://[^/]+' + re.escape(driver.get_absolute_url()) + r'(\?.*)?$'])
    except Exception:
        pass
