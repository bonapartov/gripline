"""Сборка контекста для медиа-кита пилота (PDF, см. website/services/pdf.py).

Переиспользует существующие расчёты (класс-рейтинги, титулы) — ничего не
пересчитывает заново, только добавляет специфичную для медиа-кита агрегацию
(лесенка Career highlights, топ-3 сезона, статус текущих классов), которой
раньше в проекте не было. См. CLAUDE.md → «Медиа-кит пилота».
"""
import datetime

from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone

from website.models import AnalyticsSettings, EventOccurrence, RaceResult
from website.views import (
    _get_driver_best_title,
    _get_driver_class_ratings,
    _get_driver_track_records,
)

# Сколько записей показываем в новых блоках «Титулы и достижения» / «Рекорды
# круга» (добавлены по референсу вёрстки — раздел 8 ТЗ мокапа не описывал их
# текстом, ограничение на 1 страницу из раздела 2 ТЗ допускает 2-ю при длинной
# истории, поэтому кап не жёсткий, а разумный запас).
TITLES_MAX = 6
TRACK_RECORDS_MAX = 6

# Порог «стабильности» для топ-5 берётся вдвое меньшим, чем для топ-10
# (mediakit_top10_min_field в AnalyticsSettings) — раздел 4.3 ТЗ v1.0.
STABILITY_MIN_RACES = 5
STABILITY_MIN_RATE = 0.6


def _driver_results(driver):
    return list(
        RaceResult.objects.filter(driver=driver)
        .select_related('group__page', 'group__race_class', 'team', 'chassis_new')
        .annotate(
            event_date=Subquery(
                EventOccurrence.objects.filter(
                    event_id=OuterRef('group__page_id')
                ).order_by('-end').values('end')[:1]
            ),
            group_size=Count('group__class_results'),
        )
        .order_by('-event_date', '-group__page__last_published_at')
    )


def _result_date(result):
    return (
        getattr(result, 'event_date', None)
        or result.group.page.last_published_at
        or result.group.page.first_published_at
    )


def _is_finished(result):
    return result.final_status not in ('DNF', 'DQ')


def _subtitle_line(city, team, karting_since_year):
    """«Город · Команда «X» · В картинге с {год} года» — собирается строкой
    здесь, а не условными вставками в шаблоне, чтобы отсутствующий город не
    оставлял висячий « · » перед следующей частью."""
    parts = []
    if city:
        parts.append(city)
    if team:
        parts.append(f'Команда «{team.name}»')
    if karting_since_year:
        parts.append(f'В картинге с {karting_since_year} года')
    return ' · '.join(parts)


def _header_data(driver, results):
    """Номер, команда — из самого свежего результата; год начала — из самого
    раннего; текущий класс(-ы) — класс(-ы) этого самого свежего результата
    (несколько, если пилот выступал в двух классах на одном этапе)."""
    if not results:
        return {
            'race_number': None,
            'team': None,
            'current_classes': [],
            'karting_since_year': None,
            'subtitle': _subtitle_line(driver.city, None, None),
        }

    dated = [(r, _result_date(r)) for r in results]
    dated = [(r, d) for r, d in dated if d]
    if not dated:
        return {
            'race_number': results[0].race_number,
            'team': results[0].team,
            'current_classes': [],
            'karting_since_year': None,
            'subtitle': _subtitle_line(driver.city, results[0].team, None),
        }

    latest_date = max(d for _, d in dated)
    latest_results = [r for r, d in dated if d == latest_date]
    earliest_date = min(d for _, d in dated)

    current_classes = sorted({r.group.race_class.name for r in latest_results})
    team = latest_results[0].team
    karting_since_year = earliest_date.year

    return {
        'race_number': latest_results[0].race_number,
        'team': team,
        'current_classes': current_classes,
        'karting_since_year': karting_since_year,
        'subtitle': _subtitle_line(driver.city, team, karting_since_year),
    }


def _stability_highlight(results, settings):
    """«Стабильно топ-5/топ-10» — только если типичное поле достаточно большое
    и доля попаданий высокая, иначе формулировка была бы нечестной (раздел 4.3)."""
    threshold_10 = settings.mediakit_top10_min_field
    threshold_5 = max(threshold_10 // 2, 1)

    def _tier(threshold, top_n):
        qualifying = [
            r for r in results
            if r.group_size and r.group_size >= threshold and _is_finished(r)
        ]
        if len(qualifying) < STABILITY_MIN_RACES:
            return None
        hits = sum(1 for r in qualifying if r.position <= top_n)
        rate = hits / len(qualifying)
        if rate < STABILITY_MIN_RATE:
            return None
        return {'top_n': top_n, 'min_field': threshold, 'races': len(qualifying), 'rate': round(rate * 100, 1)}

    return _tier(threshold_5, 5) or _tier(threshold_10, 10)


def _fallback_highlights(results):
    """Гарантированный фолбэк — лучший результат карьеры и/или лучший круг.
    Используется, только если титул/подиум/стабильность не применимы."""
    items = []

    finished = [r for r in results if _is_finished(r)]
    if finished:
        best_position = min(r.position for r in finished)
        best_result = max(
            (r for r in finished if r.position == best_position),
            key=lambda r: _result_date(r) or timezone.now(),
        )
        items.append({'type': 'best_result', 'position': best_position, 'result': best_result})

    lap_results = [r for r in results if r.best_lap_all_ms]
    if lap_results:
        best_lap_result = min(lap_results, key=lambda r: r.best_lap_all_ms)
        items.append({
            'type': 'best_lap',
            'lap_ms': best_lap_result.best_lap_all_ms,
            'track': getattr(best_lap_result.group.page, 'track', None),
            'class_name': best_lap_result.group.race_class.name,
            'result': best_lap_result,
        })

    return items


def _career_highlights_ladder(driver, results, podiums, podium_percentage, settings):
    """Иерархия «покажи лучшую применимую ступень» (раздел 4.3 ТЗ v1.0):
    Титул → Подиум → Стабильность → фолбэк (лучший результат и/или круг).
    Возвращает список из 1-2 элементов, минимум 1 если у пилота есть заезды."""
    title = _get_driver_best_title(driver)
    if title:
        return [{'type': 'title', **title}]

    if podiums > 0:
        return [{'type': 'podiums', 'count': podiums, 'percentage': podium_percentage}]

    stability = _stability_highlight(results, settings)
    if stability:
        return [{'type': 'stability', **stability}]

    return _fallback_highlights(results)


def _ratings_last_12_months(driver):
    """Рейтинг по классам, в которых пилот выступал за последние 12 месяцев
    (не за всю карьеру — раздел 4.5 ТЗ v1.0, чтобы в буклет не попадали
    устаревшие баллы по давно оставленному классу)."""
    class_ratings = _get_driver_class_ratings(driver)
    cutoff = timezone.now().date() - datetime.timedelta(days=365)

    recent = []
    for cr in class_ratings:
        last_race_date = cr['last_race_date']
        if not last_race_date:
            continue
        d = last_race_date.date() if hasattr(last_race_date, 'date') else last_race_date
        if d >= cutoff:
            recent.append(cr)

    recent.sort(key=lambda cr: cr['last_race_date'], reverse=True)
    return recent


def _top3_season_results(results):
    """Топ-3 финиша последнего сезона, за который есть результаты (не
    календарный год — раздел 4.6, чтобы в межсезонье блок не был пустым)."""
    dated = [(r, _result_date(r)) for r in results]
    dated = [(r, d) for r, d in dated if d]
    if not dated:
        return {'season': None, 'results': []}

    latest_season = max(d.year for _, d in dated)
    season_results = [r for r, d in dated if d.year == latest_season and _is_finished(r)]
    season_results.sort(key=lambda r: r.position)

    return {'season': latest_season, 'results': season_results[:3]}


def _titles_and_achievements(driver):
    """Хронологический список ВСЕХ топ-3 мест пилота во всех чемпионатах и
    классах (не только лучший титул — тот уже в Career highlights). Новый
    блок, добавлен по референсу вёрстки, в исходном текстовом ТЗ не описан.

    Источник — тот же ChampionshipPage.get_champions_by_class(), что и
    Career highlights/титул (кэш standings_cache, см. update_championship_standings),
    champions уже приходит top-3 на класс за сезон — доп. фильтрации не нужно."""
    from website.models import ChampionshipPage

    entries = []
    for champ in ChampionshipPage.objects.live():
        for year in champ.get_years():
            champions_by_class = champ.get_champions_by_class(year)
            for class_id, data in champions_by_class.items():
                for c in data['champions']:
                    if c['driver'].id != driver.id:
                        continue
                    entries.append({
                        'year': year,
                        'position': c['position'],
                        'championship': champ,
                        'class_name': data['name'],
                        'starts': c['starts'],
                    })

    entries.sort(key=lambda e: (-e['year'], e['position']))
    return entries[:TITLES_MAX]


def _track_records_for_mediakit(driver):
    """Рекорды трасс пилота — только те, что он ДЕРЖИТ сейчас (active/locked).
    Переиспользует существующий _get_driver_track_records(); 'beaten' (кто-то
    уже перебил) в рекламный документ включать бессмысленно — раздел 8 ТЗ
    мокапа блок не описывал, добавлен по референсу вёрстки."""
    records = _get_driver_track_records(driver)
    current = [r for r in records if r['status'] in ('active', 'locked')]
    return current[:TRACK_RECORDS_MAX]


def build_mediakit_context(driver):
    """Точка входа: собирает весь контекст для шаблона медиа-кита."""
    results = _driver_results(driver)
    settings = AnalyticsSettings.get()

    total_starts = len(results)
    wins = sum(1 for r in results if r.position == 1)
    podiums = sum(1 for r in results if r.position in (1, 2, 3))
    podium_percentage = round(podiums / total_starts * 100, 1) if total_starts else 0
    win_percentage = round(wins / total_starts * 100, 1) if total_starts else 0

    header = _header_data(driver, results)
    highlights = _career_highlights_ladder(driver, results, podiums, podium_percentage, settings)

    return {
        'driver': driver,
        'header': header,
        'highlights': highlights,
        'stats': {
            'total_starts': total_starts,
            'wins': wins,
            'podiums': podiums,
            'win_percentage': win_percentage,
            'podium_percentage': podium_percentage,
        },
        'ratings': _ratings_last_12_months(driver),
        'top3_season': _top3_season_results(results),
        'titles_and_achievements': _titles_and_achievements(driver),
        'track_records': _track_records_for_mediakit(driver),
        'profile_url': driver.get_absolute_url(),
        'generated_at': timezone.now(),
    }
