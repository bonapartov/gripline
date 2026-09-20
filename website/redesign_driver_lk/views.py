"""
Изолированная песочница редизайна ЛК пилота (компоновка по образцу DriverDB).

Живёт полностью отдельно от website/views.py::driver_detail_view и
website/templates/coderedcms/snippets/driver_page.html — ничего в них не
меняет. Переиспользует существующие функции подсчёта данных (рейтинги,
рекорды трасс, career highlights, титулы, владение медиа-китом), а не
дублирует бизнес-логику. Единственное, что скопировано — «клей» сборки
контекста, который в driver_detail_view записан инлайн (запрос results,
счётчики wins/podiums/total_starts, driver_class_periods, history_data):
эта функция не вынесена в переиспользуемый хелпер, а трогать views.py для
временной песочницы не нужно.

Если новый дизайн не подойдёт — удалить весь пакет website/redesign_driver_lk/,
website/templates/redesign_driver_lk/, website/static/website/redesign_driver_lk/
и одну строку в website/urls.py. Прод (/drivers/<slug>/) не затронут никогда.
"""
import zoneinfo

from django.db.models import Count, OuterRef, Subquery
from django.shortcuts import get_object_or_404, render
from wagtail.models import Site
from wagtailcache.cache import nocache_page

from accounts.models import UserProfile
from website.models import AnalyticsMetadata, Driver, EventOccurrence, RaceClass, RaceResult, Team
from website.mediakit_views import _is_mediakit_owner
from website.services.mediakit import _titles_and_achievements
from website.views import (
    _compute_driver_current_teams,
    _get_driver_best_title,
    _get_driver_career_highlights,
    _get_driver_class_ratings,
    _get_driver_track_records,
)


def _nearby_class_rivals(driver, class_id, count=5):
    """5 ближайших по месту в рейтинге пилотов в этом классе (не считая
    самого пилота) — блок «Соперники» референса (driverdb.com), в один ряд.

    Копия ranking-формулы _get_driver_class_ratings (website/views.py:1136) —
    та же Байесовская смесь C=15 (n*bt_score + 15*медиана) / (n+15), тот же
    источник Driver.rating_by_class, чтобы места совпадали с тем, что уже
    показано на странице («Место в рейтинге», карточки класса). Дублирование
    сознательное: _get_driver_class_ratings отдаёт только driver_above/below
    (по 1 соседу), не окно из 5, а сама функция — чистая формула без побочных
    эффектов, трогать views.py ради временной песочницы не нужно.
    """
    import json
    import statistics as _stats

    C = 15
    class_id_str = str(class_id)
    all_drivers = (
        Driver.objects.exclude(rating_by_class={})
        .only('id', 'first_name', 'last_name', 'slug', 'photo', 'city', 'rating_by_class')
    )
    entries = []
    for d in all_drivers:
        d_rbc = d.rating_by_class or {}
        if isinstance(d_rbc, str):
            try:
                d_rbc = json.loads(d_rbc)
            except Exception:
                d_rbc = {}
        if class_id_str not in d_rbc:
            continue
        entry = d_rbc[class_id_str]
        entries.append({
            'driver': d,
            'bt_score': float(entry.get('score', 0.0)),
            'starts': int(entry.get('starts', 0)),
        })
    if not entries:
        return []

    mu = _stats.median(e['bt_score'] for e in entries)
    for e in entries:
        n = e['starts']
        e['smoothed'] = (n * e['bt_score'] + C * mu) / (n + C)
    entries.sort(key=lambda x: x['smoothed'], reverse=True)

    min_s = min(e['smoothed'] for e in entries)
    max_s = max(e['smoothed'] for e in entries)
    rng = max_s - min_s if max_s != min_s else 1.0
    total = len(entries)
    for i, e in enumerate(entries):
        e['rank'] = i + 1
        e['normalized'] = round((e['smoothed'] - min_s) / rng * 100, 1)

    target = next((e for e in entries if e['driver'].id == driver.id), None)
    if target is None:
        return []

    others = [e for e in entries if e is not target]
    others.sort(key=lambda e: abs(e['rank'] - target['rank']))
    nearby = sorted(others[:count], key=lambda e: e['rank'])

    return [{
        'driver': e['driver'],
        'rank': e['rank'],
        'total': total,
        'normalized_score': e['normalized'],
        'starts': e['starts'],
    } for e in nearby]


@nocache_page
def driver_detail_v2_view(request, slug):
    """Песочница нового макета страницы пилота. Персонализированный контент
    (кнопка медиа-кита, кнопка «Заявить профиль») → @nocache_page обязателен,
    иначе wagtailcache отдаст первый закэшированный ответ всем подряд."""
    driver = get_object_or_404(Driver, slug=slug)
    current_site = Site.find_for_request(request)

    # Дата последнего пересчёта рейтингов сайта — копия глюя driver_detail_view.
    last_update = None
    try:
        last_update_utc = AnalyticsMetadata.objects.get(key='last_updated').value
        last_update = last_update_utc.astimezone(zoneinfo.ZoneInfo('Europe/Moscow'))
    except AnalyticsMetadata.DoesNotExist:
        pass

    results = RaceResult.objects.filter(driver=driver).select_related(
        'group__page',
        'group__race_class',
        'team',
        'chassis_new',
    ).annotate(
        event_date=Subquery(
            EventOccurrence.objects.filter(
                event_id=OuterRef('group__page_id')
            ).order_by('-end').values('end')[:1]
        ),
        group_size=Count('group__class_results'),
    ).order_by('-event_date', '-group__page__last_published_at')

    total_starts = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1, 2, 3]).count()
    win_percentage = round((wins / total_starts * 100), 1) if total_starts > 0 else 0
    podium_percentage = round((podiums / total_starts * 100), 1) if total_starts > 0 else 0

    # --- Периоды выступлений по классам (копия глюя driver_detail_view) ---
    all_driver_results = RaceResult.objects.filter(driver=driver).select_related(
        'group__race_class', 'group__page'
    )
    class_periods = {}
    for result in all_driver_results:
        class_name = result.group.race_class.name
        stage = result.group.page.get_parent().specific
        event_date = (
            getattr(stage, 'start_date', None)
            or result.group.page.last_published_at
            or result.group.page.first_published_at
        )
        class_periods.setdefault(class_name, []).append(event_date)

    driver_class_periods = []
    all_dates = sorted(d for dates in class_periods.values() for d in dates)
    latest_date = all_dates[-1] if all_dates else None
    for class_name, dates in class_periods.items():
        dates.sort()
        first_date, last_date = dates[0], dates[-1]
        if latest_date is not None and last_date == latest_date:
            period = f"{first_date.strftime('%m.%Y')} — н/в"
        else:
            period = f"{first_date.strftime('%m.%Y')} — {last_date.strftime('%m.%Y')}"
        driver_class_periods.append({'class_name': class_name, 'period': period})

    class_sort = RaceClass.sort_key_map()
    driver_class_periods.sort(key=lambda x: class_sort.get(x['class_name'], 9999))

    driver_profile = UserProfile.objects.filter(driver=driver, birth_date_public=True).first()
    is_unclaimed = not UserProfile.objects.filter(driver=driver, verified=True).exists()

    # Текущая команда — команда на самой свежей по дате гонке пилота, тот же
    # переиспользуемый хелпер, что уже применяет driver_detail_view для schema.org.
    current_team_id = _compute_driver_current_teams().get(driver.id)
    current_team = Team.objects.filter(id=current_team_id).first() if current_team_id else None

    class_ratings = _get_driver_class_ratings(driver)
    track_records = _get_driver_track_records(driver)
    career_highlights = _get_driver_career_highlights(
        driver, results, wins, podiums, total_starts, podium_percentage
    )
    titles = _titles_and_achievements(driver)
    titles_count = sum(1 for t in titles if t['position'] == 1)
    active_track_records_count = sum(1 for r in track_records if r['status'] == 'active')

    latest_class_rating = None
    if class_ratings:
        dated = [cr for cr in class_ratings if cr['last_race_date']]
        latest_class_rating = max(dated, key=lambda cr: cr['last_race_date']) if dated else class_ratings[0]

    # «В классе с» для колонки A — старт периода текущего/лидирующего класса,
    # из уже посчитанных class_periods выше (не пересчитываем заново).
    current_class_since = None
    if latest_class_rating and latest_class_rating['class_name'] in class_periods:
        current_class_since = min(class_periods[latest_class_rating['class_name']])

    # 5 осей радара — рейтинг/победы/подиумы уже посчитаны в class_ratings;
    # % поул-позиций и процентиль места — довычисляем здесь тем же простым
    # паттерном (qual_position == 1, как position == 1 для побед), без правки
    # views.py. Никаких «выдуманных» сравнений — только реальные цифры пилота,
    # как и для остальных трёх осей (см. открытый вопрос №2 в ТЗ).
    radar_pole_pct = 0
    radar_rank_pct = 0
    if latest_class_rating:
        class_id_for_radar = latest_class_rating['class_id']
        class_results_for_radar = results.filter(group__race_class_id=class_id_for_radar)
        starts_for_radar = latest_class_rating['starts']
        if starts_for_radar > 0:
            poles = class_results_for_radar.filter(qual_position=1).count()
            radar_pole_pct = round(poles / starts_for_radar * 100, 1)
        rank, total = latest_class_rating['rank'], latest_class_rating['total']
        radar_rank_pct = round((1 - (rank - 1) / total) * 100, 1) if total > 0 else 0

    # Значения для радара в data-* атрибутах (читает JS через parseFloat) —
    # LANGUAGE_CODE='ru-ru' + USE_L10N=True заставляют {{ }} рендерить числа
    # с запятой ("36,7"), а не точкой; str() на Python-float — всегда точка,
    # локаль-независимо. Нужно только для JS-потребляемых атрибутов, обычный
    # вывод чисел для человека ({{ cr.normalized_score }} и т.п.) не трогаем.
    radar_score_js = str(latest_class_rating['normalized_score']) if latest_class_rating else '0'
    radar_win_pct_js = str(latest_class_rating['win_pct']) if latest_class_rating else '0'
    radar_podium_pct_js = str(latest_class_rating['podium_pct']) if latest_class_rating else '0'
    radar_pole_pct_js = str(radar_pole_pct)
    radar_rank_pct_js = str(radar_rank_pct)

    # --- Соперники: 5 ближайших по месту в рейтинге ТЕКУЩЕГО класса ---
    nearby_rivals = (
        _nearby_class_rivals(driver, latest_class_rating['class_id'])
        if latest_class_rating else []
    )

    # --- История выступлений: тот же JSON-блоб, что и на живой странице ---
    STATUS_LABELS = {'DNF': 'DNF', 'DQ': 'DQ', 'DNS': 'DNS'}
    history_data = []
    available_seasons = set()
    for res in results:
        event_date = getattr(res, 'event_date', None) or res.group.page.last_published_at or res.group.page.first_published_at
        season = event_date.year if event_date else None
        if season:
            available_seasons.add(season)

        status = res.final_status
        position_gain = (res.start_position - res.position) if (res.start_position and res.position) else None

        best_lap_ms, best_lap_session = None, None
        if res.best_lap_ms:
            best_lap_ms, best_lap_session = res.best_lap_ms, 'final'
        elif res.pre_final_best_lap_ms:
            best_lap_ms, best_lap_session = res.pre_final_best_lap_ms, 'pre_final'
        elif res.qual_best_lap_ms:
            best_lap_ms, best_lap_session = res.qual_best_lap_ms, 'qual'

        has_lap_chart = bool(
            res.race_number and res.race_number in res.group.lap_chart_race_numbers()
        )

        history_data.append({
            'date': event_date.isoformat() if event_date else None,
            'date_display': event_date.strftime('%d.%m.%Y') if event_date else '—',
            'season': season,
            'class_id': res.group.race_class_id,
            'class_name': res.group.race_class.name,
            'competition_name': res.group.page.title,
            'competition_url': res.group.page.url,
            'race_number': res.race_number or None,
            'position': res.position,
            'qual_position': res.qual_position,
            'pre_final_position': res.pre_final_position,
            'status': status,
            'status_label': STATUS_LABELS.get(status),
            'start_position': res.start_position,
            'position_gain': position_gain,
            'pre_final_start_pos': res.pre_final_start_pos,
            'chassis_name': res.chassis_new.name if res.chassis_new else None,
            'chassis_url': res.chassis_new.get_absolute_url() if res.chassis_new else None,
            'team_name': res.team.name if res.team else None,
            'team_url': res.team.get_absolute_url() if res.team else None,
            'best_lap_ms': best_lap_ms,
            'best_lap_session': best_lap_session,
            'points': res.points,
            'group_id': res.group_id,
            'group_size': res.group_size,
            'has_lap_chart': has_lap_chart,
        })
    available_seasons = sorted(available_seasons, reverse=True)
    available_history_classes = sorted(
        {(h['class_id'], h['class_name']) for h in history_data},
        key=lambda c: c[1]
    )

    can_view_mediakit = _is_mediakit_owner(request, driver)

    return render(request, "redesign_driver_lk/driver_page_v2.html", {
        "driver": driver,
        "object": driver,
        "page": driver,  # CodeRedCMS ищет 'page' для хедера/футера сайта
        "site": current_site,
        "results": results,
        "last_update": last_update,
        "total_starts": total_starts,
        "wins": wins,
        "podiums": podiums,
        "win_percentage": win_percentage,
        "podium_percentage": podium_percentage,
        "driver_class_periods": driver_class_periods,
        "driver_profile": driver_profile,
        "current_team": current_team,
        "is_unclaimed": is_unclaimed,
        "class_ratings": class_ratings,
        "track_records": track_records,
        "active_track_records_count": active_track_records_count,
        "career_highlights": career_highlights,
        "titles": titles,
        "titles_count": titles_count,
        "latest_class_rating": latest_class_rating,
        "current_class_since": current_class_since,
        "radar_score_js": radar_score_js,
        "radar_win_pct_js": radar_win_pct_js,
        "radar_podium_pct_js": radar_podium_pct_js,
        "radar_pole_pct_js": radar_pole_pct_js,
        "radar_rank_pct_js": radar_rank_pct_js,
        "history_data": history_data,
        "available_seasons": available_seasons,
        "available_history_classes": available_history_classes,
        "can_view_mediakit": can_view_mediakit,
        "nearby_rivals": nearby_rivals,
    })
