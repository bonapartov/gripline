"""Контекст для медиа-кита команды (PDF) — ЛК команды, раздел 8 ТЗ v1.0.

Прямое расширение медиа-кита пилота: тот же формат/движок/CSS/шрифты
(services/pdf.py, шаблон только другой — team_mediakit.html), содержание —
на уровне команды. Статистика/highlights переиспользуют services/team_stats.py
(тот же код, что и публичная страница команды — team_detail_view), заново
не считаются.
"""
from collections import defaultdict

from django.utils import timezone

from website.services.team_stats import (
    compute_team_highlights,
    compute_team_stats,
    team_results,
    team_roster,
)


def _result_date(result):
    return (
        getattr(result, 'event_date', None)
        or result.group.page.last_published_at
        or result.group.page.first_published_at
    )


def _team_since_year(results):
    """Год самого раннего результата за эту команду — аналог «в картинге
    с {год}» у пилота, но на уровне команды (нет отдельного поля
    «дата основания» на модели Team)."""
    dated = [_result_date(r) for r in results]
    dated = [d for d in dated if d]
    return min(dated).year if dated else None


def _roster_rows(roster, results):
    """Компактный список ростера с текущим классом каждого пилота — класс
    берётся из его самого свежего результата ЗА ЭТУ команду; новичок без
    результатов показывается без класса."""
    by_driver = defaultdict(list)
    for r in results:
        by_driver[r.driver_id].append(r)

    rows = []
    for driver in roster:
        driver_results = by_driver.get(driver.id, [])
        class_name = None
        if driver_results:
            latest = max(driver_results, key=lambda r: _result_date(r) or timezone.now())
            class_name = latest.group.race_class.name
        rows.append({'driver': driver, 'class_name': class_name})

    rows.sort(key=lambda row: row['driver'].full_name)
    return rows


def _subtitle_line(city, since_year):
    """«Город · На Gripline с {год}» — строкой в Python, не условными
    вставками в шаблоне (тот же баг с висячим « · », что уже чинили в
    подзаголовке медиа-кита пилота)."""
    parts = []
    if city:
        parts.append(city)
    if since_year:
        parts.append(f'На Gripline с {since_year} года')
    return ' · '.join(parts)


def build_mediakit_context(team):
    """Точка входа: собирает весь контекст для шаблона медиа-кита команды."""
    roster = list(team_roster(team))
    results = team_results(team, roster)

    stats = compute_team_stats(results)
    highlights = compute_team_highlights(team, roster, results)
    since_year = _team_since_year(results)

    return {
        'team': team,
        'since_year': since_year,
        'roster_count': len(roster),
        'subtitle': _subtitle_line(team.city, since_year),
        'roster': _roster_rows(roster, results),
        'stats': stats,
        'highlights': highlights,
        'profile_url': team.get_absolute_url(),
        'generated_at': timezone.now(),
    }
