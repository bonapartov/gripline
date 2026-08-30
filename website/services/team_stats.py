"""Агрегированная статистика и highlights команды — ЛК команды, разделы 5-6
ТЗ v1.0. Переиспользует существующий расчёт «текущего ростера»
(_get_current_team_driver_ids) и общую лесенку highlights (services/highlights.py),
которую уже использует медиа-кит пилота — не дублируем.

Период — вся история (подтверждено с пользователем 2026-08-30): на этой
странице раньше был мёртвый код `twelve_months_ago`, который никогда не
применялся к фильтрации, и вводящий в заблуждение текст в шаблоне
(«за последние 12 месяцев») — оба исправлены заодно с этой фичей.

Скоуп результатов — RaceResult.team == эта команда (не «все результаты
пилотов ростера когда-либо, за любую команду») — так уже считался блок
«Пилоты по классам» на этой странице (team_detail_view), для консистентности
статистика и highlights используют тот же скоуп. Титул — исключение (см.
_team_best_title): титулы не привязаны к команде в модели данных
(ChampionshipPage.get_champions_by_class не хранит команду), поэтому берём
любой титул пилота из ТЕКУЩЕГО ростера, даже выигранный до перехода в
команду — это честный «у нас в составе есть чемpion», не приписывание
чужого результата команде.
"""
from django.db.models import Count, OuterRef, Subquery

from website.models import AnalyticsSettings, EventOccurrence, RaceResult
from website.services.highlights import fallback_highlights, is_finished, stability_highlight
from website.views import _get_current_team_driver_ids, _get_driver_best_title


def team_roster(team, current_team_map=None):
    from website.models import Driver

    return Driver.objects.filter(
        id__in=_get_current_team_driver_ids(team, current_team_map)
    ).distinct()


def team_results(team, roster):
    """Результаты ростера ЗА ЭТУ команду (RaceResult.team == team), не вся
    карьера пилотов — см. пояснение в модуле."""
    return list(
        RaceResult.objects.filter(team=team, driver__in=roster)
        .select_related('group__page', 'group__race_class', 'driver')
        .annotate(
            event_date=Subquery(
                EventOccurrence.objects.filter(
                    event_id=OuterRef('group__page_id')
                ).order_by('-end').values('end')[:1]
            ),
            group_size=Count('group__class_results'),
        )
    )


def compute_team_stats(results):
    """Прямой аналог блока «Статистика пилота» (раздел 5 ТЗ), суммированный
    по всему ростеру за всю историю выступлений за эту команду."""
    total_starts = len(results)
    wins = sum(1 for r in results if r.position == 1)
    podiums = sum(1 for r in results if r.position in (1, 2, 3))
    return {
        'total_starts': total_starts,
        'wins': wins,
        'podiums': podiums,
        'win_percentage': round(wins / total_starts * 100, 1) if total_starts else 0,
        'podium_percentage': round(podiums / total_starts * 100, 1) if total_starts else 0,
    }


def _team_best_title(roster):
    """Титул — если кто-то из ТЕКУЩЕГО ростера когда-либо взял 1-е место в
    сезоне/классе (раздел 6, п.1) — не привязан к результатам «за эту
    команду», см. пояснение в модуле. Несколько чемпионов в ростере — берём
    самый свежий титул."""
    best = None
    for driver in roster:
        title = _get_driver_best_title(driver)
        if title and (best is None or title['year'] > best['year']):
            best = {**title, 'driver': driver}
    return best


def _team_best_podium(results):
    """Подиум — лучший подиумный результат среди пилотов команды (раздел 6,
    п.2): одна конкретная строка (место + этап + пилот), не счётчик — в
    отличие от лесенки медиа-кита пилота, где это счётчик подиумов."""
    podium_results = [r for r in results if r.position in (1, 2, 3) and is_finished(r)]
    if not podium_results:
        return None
    best_position = min(r.position for r in podium_results)
    best = max(
        (r for r in podium_results if r.position == best_position),
        key=lambda r: getattr(r, 'event_date', None) or r.group.page.last_published_at or r.group.page.first_published_at,
    )
    return {'position': best_position, 'result': best}


def compute_team_history(results):
    """История выступлений команды (раздел 7 ТЗ): агрегация по этапу
    (EventPage), не по пилоту — этап → какие пилоты команды участвовали →
    лучший результат команды на этом этапе. «Лучший результат» исключает
    DNF/DQ (тот же принцип, что best_result в Career highlights пилота) —
    если весь состав сошёл на этапе, лучшего числового результата нет.

    Ход гонки: у одного этапа может быть несколько групп (разные классы) —
    lap chart — per-group данные, поэтому на каждую группу, где есть данные
    (group.lap_chart_race_numbers()), отдельный триггер с race_number'ами
    ВСЕХ пилотов команды в этой группе (multi-select виджета)."""
    from collections import defaultdict

    by_event = defaultdict(list)
    for r in results:
        by_event[r.group.page_id].append(r)

    rows = []
    for page_id, event_results in by_event.items():
        page = event_results[0].group.page
        event_date = (
            getattr(event_results[0], 'event_date', None)
            or page.last_published_at
            or page.first_published_at
        )

        drivers_in_event = sorted(
            {(r.driver_id, r.driver.full_name, r.driver.get_absolute_url()) for r in event_results},
            key=lambda x: x[1],
        )

        finished = [r for r in event_results if is_finished(r)]
        pool = finished or event_results
        best = min(pool, key=lambda r: r.position)

        by_group = defaultdict(list)
        for r in event_results:
            by_group[r.group_id].append(r)

        lap_chart_groups = []
        for group_id, group_results in by_group.items():
            group = group_results[0].group
            available = group.lap_chart_race_numbers()
            race_numbers = [
                r.race_number for r in group_results
                if r.race_number and r.race_number in available
            ]
            if race_numbers:
                lap_chart_groups.append({
                    'group_id': group_id,
                    'class_name': group.race_class.name,
                    'race_numbers': race_numbers,
                })

        rows.append({
            'event': page,
            'event_date': event_date,
            'drivers': [{'id': d[0], 'name': d[1], 'url': d[2]} for d in drivers_in_event],
            'best_result': best,
            'best_finished': bool(finished),
            'lap_chart_groups': lap_chart_groups,
        })

    rows.sort(key=lambda row: row['event_date'] or row['event'].first_published_at, reverse=True)
    return rows


def compute_team_highlights(team, roster, results):
    """Иерархия «покажи лучшую применимую ступень» (раздел 6 ТЗ):
    Титул → лучший подиум → стабильность → фолбэк (лучший результат и/или круг).
    Возвращает список из 1-2 элементов, минимум 1 если у команды есть результаты."""
    title = _team_best_title(roster)
    if title:
        return [{'type': 'title', **title}]

    best_podium = _team_best_podium(results)
    if best_podium:
        return [{'type': 'podium', **best_podium}]

    settings = AnalyticsSettings.get()
    stability = stability_highlight(results, settings)
    if stability:
        return [{'type': 'stability', **stability}]

    return fallback_highlights(results)
