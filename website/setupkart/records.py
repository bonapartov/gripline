"""Рекорды трасс для приложения SetupKart (решение 08.10.2026): под эталоном круга — строка
«Рекорд трассы (класс)», по нажатию — окно с подробностями.

Источник — Track.records_cache (команда update_track_records, тот же расчёт, что у блока
«Рекорды трасс» на сайте). Пустые поля не отдаются — приложение их не показывает. Двигатель, шины
и погода записаны на класс на этапе, не на пилота — приложение подписывает их «на этапе».
"""
from django.conf import settings

from website.models import RaceResult
from website.services.demo import DEMO_DRIVER_SLUG_PREFIX

SESSION_LABELS = {'qual': 'Квалификация', 'pre_final': 'Предфинал', 'final': 'Финал'}


def _abs(url):
    if not url:
        return ''
    return url if url.startswith('http') else f"{settings.BASE_URL.rstrip('/')}{url}"


def _weather(group):
    parts = []
    if group.air_temperature is not None:
        parts.append(f"{group.air_temperature:+.0f} °C")
    if group.humidity is not None:
        parts.append(f"влажность {group.humidity}%")
    if group.precipitation is not None:
        parts.append('без осадков' if group.precipitation == 0 else f"осадки {group.precipitation:g} мм")
    return ', '.join(parts)


def records_by_track(tracks):
    """{track_id: [рекорд по классу, …]} для трасс приложения; без рекордов — трассы нет в словаре."""
    wanted = {}
    for t in tracks:
        for class_id, rec in (t.records_cache or {}).items():
            if rec.get('result_id') and rec.get('lap_ms'):
                wanted[rec['result_id']] = (t.pk, class_id, rec)
    if not wanted:
        return {}
    results = {r.pk: r for r in RaceResult.objects.filter(pk__in=wanted).select_related(
        'driver', 'chassis_new', 'group__race_class', 'group__engine', 'group__tyre', 'group__page')}
    out = {}
    for result_id, (track_id, class_id, rec) in wanted.items():
        r = results.get(result_id)
        if r is None or r.driver.slug and r.driver.slug.startswith(DEMO_DRIVER_SLUG_PREFIX):
            continue  # удалён после пересчёта (ждём update_track_records) или демо-пилот
        g = r.group
        item = {
            'class_id': g.race_class_id,
            'class_name': g.race_class.name,
            'lap_ms': rec['lap_ms'],
            'driver': r.driver.full_name,
            'driver_url': _abs(r.driver.get_absolute_url()),
            'date': rec.get('record_date') or '',
            'session': SESSION_LABELS.get(r.best_lap_session or '', ''),
            'event': g.page.title,
            'event_url': _abs(g.page.url),
            'chassis': r.chassis_new.name if r.chassis_new else '',
            'engine': str(g.engine) if g.engine else '',
            'tyre': str(g.tyre) if g.tyre else '',
            'weather': _weather(g),
        }
        out.setdefault(track_id, []).append({k: v for k, v in item.items() if v not in ('', None)})
    for items in out.values():
        items.sort(key=lambda x: x['class_name'])
    return out
