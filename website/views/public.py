"""Публичные страницы пилотов, команд, трасс, техники и сравнений."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from website.models import Ad, AdCategory, AdResponse
from django.db.models import Q
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import path
from wagtail.snippets.views.snippets import SnippetViewSet
from website.models import (
    Driver, Team, RaceResult, RaceClass, Track, Chassis, TyreBrand, TyreType,
    Tyre, Engine,
)
from django.utils.timezone import now
# Определение текущего сайта нужно для Header/Footer.
from wagtail.models import Site
from django.db.models import F, OuterRef, Subquery, Avg
from website.models import EventOccurrence
from django.db import models
from django.utils import timezone
import zoneinfo
from website.models import AnalyticsMetadata, AnalyticsSettings
from datetime import timedelta
from django.db.models import Max
from website.models import TeamStaff, TeamStaffMembership
from django.http import JsonResponse
from django.db.models import Count
from .common import (
    _compute_driver_current_teams, _get_current_team_driver_ids,
)
from .ratings import (
    _career_stat_percentiles, _class_stat_percentiles,
    _get_driver_career_highlights, _get_driver_class_ratings,
    _get_driver_track_records, _nearby_class_rivals, get_chassis_stats,
)

def public_training_sessions(driver):
    """Тренировки из приложения, которые пилот открыл на своей странице (website/setupkart/public.py)."""
    from website.setupkart.public import training_sessions
    return training_sessions(driver)


def driver_detail_view(request, slug):
    driver = get_object_or_404(Driver, slug=slug)

    # Пытаемся найти текущий сайт, чтобы CMS могла подтянуть верное меню
    current_site = Site.find_for_request(request)

    # Получаем дату окончания для каждого этапа
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

    # --- РАСЧЕТ СТАТИСТИКИ ---
    total_starts = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1, 2, 3]).count()

    # Расчет процентов (защита от деления на ноль)
    win_percentage = round((wins / total_starts * 100), 1) if total_starts > 0 else 0
    podium_percentage = round((podiums / total_starts * 100), 1) if total_starts > 0 else 0

    # Получаем дату последнего глобального обновления
    last_update = None
    try:
        last_update_utc = AnalyticsMetadata.objects.get(key='last_updated').value
        last_update = last_update_utc.astimezone(zoneinfo.ZoneInfo('Europe/Moscow'))
    except AnalyticsMetadata.DoesNotExist:
        pass

    # --- Периоды выступлений по классам ---
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

    # Дата рождения на публичной странице — только если пилот явно разрешил
    # (UserProfile.birth_date_public), иначе профиль вообще не подтягиваем.
    from accounts.models import UserProfile
    driver_profile = UserProfile.objects.filter(driver=driver, birth_date_public=True).first()
    is_unclaimed = not UserProfile.objects.filter(driver=driver, verified=True).exists()

    # Текущая команда — команда на самой свежей по дате гонке пилота, тот же
    # переиспользуемый хелпер, что уже применяет schema.org Person ниже.
    current_team_id = _compute_driver_current_teams().get(driver.id)
    current_team = Team.objects.filter(id=current_team_id).first() if current_team_id else None

    class_ratings = _get_driver_class_ratings(driver)
    track_records = _get_driver_track_records(driver)
    career_highlights = _get_driver_career_highlights(
        driver, results, wins, podiums, total_starts, podium_percentage
    )

    from website.services.mediakit import _titles_and_achievements
    titles = _titles_and_achievements(driver)
    titles_count = sum(1 for t in titles if t['position'] == 1)
    active_track_records_count = sum(1 for r in track_records if r['status'] == 'active')

    # Самая свежая по дате гонки карточка рейтинга — для «Текущей формы»/шапки на Обзоре
    latest_class_rating = None
    if class_ratings:
        dated = [cr for cr in class_ratings if cr['last_race_date']]
        latest_class_rating = max(dated, key=lambda cr: cr['last_race_date']) if dated else class_ratings[0]

    # «В классе с» — старт периода текущего/лидирующего класса, из уже
    # посчитанных class_periods выше (не пересчитываем заново).
    current_class_since = None
    if latest_class_rating and latest_class_rating['class_name'] in class_periods:
        current_class_since = min(class_periods[latest_class_rating['class_name']])

    # --- Топ-5/Топ-10 в текущем/лидирующем классе — замена бесполезного тайла
    # «Личный лучший круг» (время круга не сравнимо между разными трассами/
    # классами, никакой «достижительной» ценности не несёт в отличие от
    # соседних тайлов-счётчиков карьеры). DNF/DQ исключены — тот же принцип,
    # что у best_result в career_highlights (сошёл — не финиш в топе). ---
    top5_count = 0
    top10_count = 0
    if latest_class_rating:
        class_finishes = results.filter(
            group__race_class_id=latest_class_rating['class_id']
        ).exclude(final_status__in=['DNF', 'DQ'])
        top5_count = class_finishes.filter(position__gte=1, position__lte=5).count()
        top10_count = class_finishes.filter(position__gte=1, position__lte=10).count()

    # --- Поулы/Финиши/DNF за карьеру — тайлы Обзора (тот же career-wide скоуп,
    # что у Стартов/Побед/Подиумов). DNF/DQ — сходы, DNS в знаменатель «финишей»
    # не считаем неудачей отдельно (тот же принцип, что и в top5/top10 выше). ---
    poles_count = results.filter(qual_position=1).count()
    dnf_count = results.filter(final_status__in=['DNF', 'DQ']).count()
    finished_count = total_starts - dnf_count
    dnf_ratio_value = round(dnf_count / total_starts * 100, 1) if total_starts > 0 else 0

    # --- Перцентили карьеры («лучше, чем N% пилотов») для тайлов Обзора;
    # None ниже порога стартов — тайлы просто не покажут подпись.
    career_percentiles = _career_stat_percentiles(
        driver, total_starts, wins, podiums, poles_count, finished_count, dnf_ratio_value
    )

    # --- Перцентили внутри текущего класса — источник и для радара «Профиль
    # результатов» в режиме «Класс», и для тайлов Обзора в том же режиме. ---
    class_percentiles = (
        _class_stat_percentiles(driver, latest_class_rating['class_id'])
        if latest_class_rating else None
    )
    # LANGUAGE_CODE='ru-ru' + USE_L10N=True заставляют {{ }} рендерить числа
    # с запятой ("36,7"), а не точкой; str() на Python-float — всегда точка,
    # локаль-независимо. Нужно только для JS-потребляемых data-* атрибутов
    # радара — тайлы рендерятся обычным {{ }}, JS их не читает.
    # Сырые значения — тут же, рядом с процентилем на каждой оси, чтобы
    # «Победы 100%» не висело без якоря (нашли на живом примере: 7 побед —
    # максимум в классе, отсюда 100%, но без самого числа «7» выглядит как баг).
    radar_class_js = (
        {
            **{k: str(class_percentiles[k]) for k in ('starts_pct', 'wins_pct', 'podiums_pct', 'poles_pct', 'rating_pct')},
            'starts_raw': str(class_percentiles['starts']),
            'wins_raw': str(class_percentiles['wins']),
            'podiums_raw': str(class_percentiles['podiums']),
            'poles_raw': str(class_percentiles['poles']),
            'rating_raw': str(latest_class_rating['normalized_score']),
        }
        if class_percentiles else {}
    )
    # Радар в режиме «Карьера» — те же 4 оси (Старты/Победы/Подиумы/Поулы),
    # пятая ось подменена с «Рейтинг» на «Финишей»: у BT-рейтинга нет
    # карьерного эквивалента (нет кросс-классовой модели, см. обсуждение
    # Global Ranking), а «Финишей» уже посчитан для тайлов и держит тот же
    # принцип «больше — лучше», что и остальные оси (в отличие от DNF, где
    # шкалу пришлось бы инвертировать). Форма радара остаётся 5-точечной
    # в обоих режимах — меняются только данные и подпись пятой оси.
    radar_career_js = (
        {
            'starts_pct': str(career_percentiles['starts']),
            'wins_pct': str(career_percentiles['wins']),
            'podiums_pct': str(career_percentiles['podiums']),
            'poles_pct': str(career_percentiles['poles']),
            'rating_pct': str(career_percentiles['finished']),
            'starts_raw': str(total_starts),
            'wins_raw': str(wins),
            'podiums_raw': str(podiums),
            'poles_raw': str(poles_count),
            'rating_raw': str(finished_count),
        }
        if career_percentiles else {}
    )
    # Дефолтный режим тумблера — «Класс», если для него есть данные (обычный
    # случай); иначе «Карьера», чтобы кнопка по умолчанию не указывала на
    # пустую/задизейбленную вкладку (см. driver_page.html — кнопка «Класс»
    # дизейблится именно когда class_percentiles нет).
    default_scope = 'class' if class_percentiles else 'career'

    # --- Соперники: 5 ближайших по месту в рейтинге текущего класса ---
    nearby_rivals = (
        _nearby_class_rivals(driver, latest_class_rating['class_id'])
        if latest_class_rating else []
    )

    # --- История выступлений: одна JSON-выдача, вся фильтрация/пагинация на клиенте ---
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

    from website.schema import driver_person_dict, render_json_ld, _absolute_url

    # Локальный импорт — см. комментарий в DriverViewSet.get_urlpatterns()
    # про циклический импорт website.mediakit_views <-> website.views.
    from website.mediakit_views import _is_mediakit_owner
    can_view_mediakit = _is_mediakit_owner(request, driver)

    driver_schema_json_ld = render_json_ld(
        driver_person_dict(driver, current_site, current_team=current_team)
    )
    driver_breadcrumb_items = [
        {"name": "Главная", "url": _absolute_url(current_site, "/")},
        # /drivers/ (индекс сниппета) отдаёт 403 анонимам/краулерам — используем
        # реальную публичную страницу вместо неё.
        {"name": "Пилоты", "url": _absolute_url(current_site, "/top/drivers/")},
        {"name": driver.full_name, "url": _absolute_url(current_site, driver.get_absolute_url())},
    ]

    # Текущий класс — класс самой свежей по дате гонки (results отсортированы по дате убыв.)
    from website.seo_meta import driver_seo
    seo_class = history_data[0]['class_name'] if history_data else None
    driver_seo_meta = driver_seo(
        driver, current_site,
        current_class=seo_class,
        current_team=current_team,
        total_starts=total_starts, wins=wins, podiums=podiums, titles_count=titles_count,
        class_rating=next((cr for cr in class_ratings if cr['class_name'] == seo_class), None),
    )

    return render(request, "coderedcms/snippets/driver_page.html", {
        "driver": driver,
        "object": driver,
        # ВАЖНО: CodeRedCMS ищет переменную 'page' для вывода Header и Footer
        "page": driver,
        "site": current_site,
        "results": results,
        "total_starts": total_starts,
        "wins": wins,
        "podiums": podiums,
        "win_percentage": win_percentage,
        "podium_percentage": podium_percentage,
        "last_update": last_update,
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
        "top5_count": top5_count,
        "top10_count": top10_count,
        "poles_count": poles_count,
        "finished_count": finished_count,
        "dnf_ratio_value": dnf_ratio_value,
        "career_percentiles": career_percentiles,
        "class_percentiles": class_percentiles,
        "radar_class_js": radar_class_js,
        "radar_career_js": radar_career_js,
        "default_scope": default_scope,
        "nearby_rivals": nearby_rivals,
        "history_data": history_data,
        "training_sessions": public_training_sessions(driver),
        "available_seasons": available_seasons,
        "available_history_classes": available_history_classes,
        "can_view_mediakit": can_view_mediakit,
        "schema_json_ld": driver_schema_json_ld,
        "breadcrumb_items": driver_breadcrumb_items,
        "seo": driver_seo_meta,
    })


def team_detail_view(request, slug):
    team = get_object_or_404(Team, slug=slug)
    current_site = Site.find_for_request(request)

    # Получаем пилотов текущего состава (по факту последнего старта, см. _get_current_team_driver_ids)
    team_drivers = Driver.objects.filter(
        id__in=_get_current_team_driver_ids(team)
    ).distinct()

    # Создаем сгруппированный словарь: {class_name: [{'driver': driver, 'period': period}]}
    driver_classes = {}

    for driver in team_drivers:
        # Получаем все результаты пилота за эту команду (без ограничения по дате)
        all_results = RaceResult.objects.filter(
            team=team,
            driver=driver
        ).select_related('group__race_class', 'group__page')

        # Группируем по классам
        class_results = {}
        for result in all_results:
            class_name = result.group.race_class.name
            if class_name not in class_results:
                class_results[class_name] = []
            class_results[class_name].append(result)

        # Для каждого класса определяем период выступлений
        for class_name, results in class_results.items():
            # Сортируем по дате
            results.sort(key=lambda x: x.group.page.last_published_at or x.group.page.first_published_at)

            first_date = results[0].group.page.last_published_at or results[0].group.page.first_published_at
            last_date = results[-1].group.page.last_published_at or results[-1].group.page.first_published_at

            # Проверяем, перешёл ли пилот в другой класс
            # Получаем все классы пилота, сортируем по дате последнего заезда
            all_driver_classes = {}
            for r in RaceResult.objects.filter(driver=driver).select_related('group__race_class'):
                class_name_driver = r.group.race_class.name
                if class_name_driver not in all_driver_classes:
                    all_driver_classes[class_name_driver] = []
                all_driver_classes[class_name_driver].append(r)

            # Находим самый поздний класс (текущий)
            latest_class = None
            latest_date = None
            for cls_name, cls_results in all_driver_classes.items():
                cls_results.sort(key=lambda x: x.group.page.last_published_at or x.group.page.first_published_at)
                cls_last_date = cls_results[-1].group.page.last_published_at or cls_results[-1].group.page.first_published_at
                if latest_date is None or cls_last_date > latest_date:
                    latest_date = cls_last_date
                    latest_class = cls_name

            # Формируем строку периода
            if class_name == latest_class:
                period = f"{first_date.strftime('%m.%Y')} — н/в"
            else:
                period = f"{first_date.strftime('%m.%Y')} — {last_date.strftime('%m.%Y')}"

            # Добавляем пилота в словарь с периодом
            if class_name not in driver_classes:
                driver_classes[class_name] = []

            # Проверяем, не добавлен ли уже пилот с таким классом
            existing = next((d for d in driver_classes[class_name] if d['driver'].id == driver.id), None)
            if not existing:
                driver_classes[class_name].append({
                    'driver': driver,
                    'period': period
                })

    class_sort = RaceClass.sort_key_map()
    sorted_driver_classes = dict(sorted(driver_classes.items(), key=lambda x: class_sort.get(x[0], 9999)))
    # Получаем активных сотрудников команды
    staff_members = TeamStaff.objects.filter(
        team_memberships__team=team,
        team_memberships__is_active=True
    ).distinct().order_by('last_name', 'first_name')

    # Для каждого сотрудника получаем его членство
    staff_list = []
    for staff in staff_members:
        membership = TeamStaffMembership.objects.filter(
            staff=staff,
            team=team,
            is_active=True
        ).first()
        staff_list.append({
            'staff': staff,
            'membership': membership,
        })

    all_drivers = Driver.objects.order_by('last_name', 'first_name')

    # Статистика и highlights команды (ЛК команды, разделы 5-6 ТЗ v1.0) —
    # переиспользуем уже вычисленный ростер team_drivers, не пересчитываем.
    from website.services.team_stats import (
        compute_team_highlights,
        compute_team_history,
        compute_team_stats,
        team_results as _team_results,
    )
    team_race_results = _team_results(team, team_drivers)
    team_stats = compute_team_stats(team_race_results)
    team_highlights = compute_team_highlights(team, team_drivers, team_race_results)
    team_history = compute_team_history(team_race_results)

    # Локальный импорт — см. комментарий в TeamViewSet.get_urlpatterns()
    # про циклический импорт website.team_mediakit_views <-> website.views.
    from website.team_mediakit_views import _is_team_manager
    can_view_team_mediakit = _is_team_manager(request, team)

    # Контекст для кнопки "Вступить в команду"
    user_driver = None
    join_status = None  # 'no_auth' | 'no_driver' | 'already_member' | 'pending' | 'ready'
    if request.user.is_authenticated:
        try:
            user_driver = request.user.profile.driver
        except Exception:
            user_driver = None
        if user_driver is None:
            join_status = 'no_driver'
        else:
            from website.models import TeamMembership
            from teams.models import TeamJoinRequest
            if TeamMembership.objects.filter(driver=user_driver, team=team, is_active=True).exists():
                join_status = 'already_member'
            elif TeamJoinRequest.objects.filter(driver=user_driver, team=team, status='pending').exists():
                join_status = 'pending'
            else:
                join_status = 'ready'
    else:
        join_status = 'no_auth'

    from website.schema import team_sportsteam_dict, render_json_ld, _absolute_url
    from website.seo_meta import team_seo

    team_schema_json_ld = render_json_ld(
        team_sportsteam_dict(team, current_site, members=team_drivers)
    )
    team_breadcrumb_items = [
        {"name": "Главная", "url": _absolute_url(current_site, "/")},
        # /teams/ (индекс сниппета) отдаёт 403 анонимам/краулерам, и публичной
        # страницы со списком команд (аналог TrackIndexPage) в проекте нет —
        # оставляем как есть, известное ограничение.
        {"name": "Команды", "url": _absolute_url(current_site, "/teams/")},
        {"name": team.name, "url": _absolute_url(current_site, team.get_absolute_url())},
    ]

    return render(request, "coderedcms/snippets/team_page.html", {
        "team": team,
        "driver_classes": sorted_driver_classes,
        "staff_members": staff_list,
        "site": current_site,
        "all_drivers": all_drivers,
        "user_driver": user_driver,
        "join_status": join_status,
        "team_stats": team_stats,
        "team_highlights": team_highlights,
        "team_history": team_history,
        "can_view_team_mediakit": can_view_team_mediakit,
        "schema_json_ld": team_schema_json_ld,
        "breadcrumb_items": team_breadcrumb_items,
        "seo": team_seo(
            team, current_site,
            classes=list(sorted_driver_classes),
            drivers_count=len(team_drivers),
            team_stats=team_stats,
        ),
    })

def track_detail_view(request, slug):
    track = get_object_or_404(Track, slug=slug)
    current_site = Site.find_for_request(request)

    from website.models import ChampionshipPage, EventPage, EventOccurrence

    now = timezone.now()

    # Получаем все события на этой трассе
    all_events = EventPage.objects.live().filter(track=track).distinct()

    # Группируем по мероприятию: ключ = (title, дата начала)
    # Одно мероприятие может иметь несколько EventPage (по одному на каждый класс)
    grouped = {}
    champ_titles = {}

    for event in all_events:
        occurrence = event.occurrences.first()

        if occurrence and occurrence.start:
            start_dt = occurrence.start
            end_dt = occurrence.end
        else:
            start_dt = event.first_published_at
            end_dt = event.first_published_at

        # Ключ группировки: название + дата начала (без времени)
        group_key = f"{event.title}_{start_dt.date()}"

        if group_key not in grouped:
            championship = event.get_parent().specific
            # Родитель — обычно StagePage («6 этап»); подпись карточки — сам чемпионат
            if championship.id not in champ_titles:
                found = ChampionshipPage.objects.ancestor_of(championship, inclusive=True).first()
                champ_titles[championship.id] = found.title if found else championship.title
            grouped[group_key] = {
                'title': event.title,
                'url': event.url,
                'start': start_dt,
                'end': end_dt,
                'championship': championship,
                'championship_title': champ_titles[championship.id],
                'classes': [],
                'is_past': end_dt < now if end_dt else start_dt < now,
            }

        # Добавляем классы из групп результатов этого EventPage
        for group in event.race_class_groups.all():
            class_name = group.race_class.name
            if class_name not in grouped[group_key]['classes']:
                grouped[group_key]['classes'].append(class_name)

    past_events = sorted(
        [v for v in grouped.values() if v['is_past']],
        key=lambda x: x['start'],
        reverse=True
    )
    upcoming_events = sorted(
        [v for v in grouped.values() if not v['is_past']],
        key=lambda x: x['start']
    )

    from website.services.track_page import build_track_page

    page_ctx = build_track_page(track, request.GET.get('class'), races_count=len(past_events))

    from website.schema import track_place_dict, render_json_ld, _absolute_url

    track_schema_json_ld = render_json_ld(track_place_dict(track, current_site))
    track_breadcrumb_items = [
        {"name": "Главная", "url": _absolute_url(current_site, "/")},
        # /tracks/ (индекс сниппета) отдаёт 403 анонимам/краулерам — используем
        # реальную публичную TrackIndexPage вместо неё.
        {"name": "Трассы", "url": _absolute_url(current_site, "/trassy/")},
        {"name": track.name, "url": _absolute_url(current_site, track.get_absolute_url())},
    ]

    from website.seo_meta import track_seo

    return render(request, "coderedcms/snippets/track_page.html", {
        "seo": track_seo(
            track, current_site,
            events_count=len(past_events) + len(upcoming_events),
            record_classes=sum(1 for c in page_ctx['classes'] if c['record']),
            next_event=upcoming_events[0] if upcoming_events else None,
        ),
        "track": track,
        "object": track,
        "page": track,
        "past_events": past_events,
        "upcoming_events": upcoming_events,
        "site": current_site,
        "schema_json_ld": track_schema_json_ld,
        "breadcrumb_items": track_breadcrumb_items,
        **page_ctx,
    })
def chassis_detail_view(request, slug):
    chassis = get_object_or_404(Chassis, slug=slug)
    current_site = Site.find_for_request(request)

    # Базовый queryset
    base_results = RaceResult.objects.filter(chassis_new=chassis).select_related(
        'driver', 'team', 'group__page', 'group__race_class',
        'group__tyre', 'group__tyre__brand', 'group__tyre__type'
    )

    # Получаем все возможные значения для фильтров
    from website.models import RaceClass, Track, Tyre

    available_classes = RaceClass.objects.filter(
        raceclassresultgroup__class_results__in=base_results
    ).distinct().order_by('sort_order', 'name')

    available_tracks = Track.objects.filter(
        events__race_class_groups__class_results__in=base_results
    ).distinct().order_by('name')

    available_tyres = Tyre.objects.filter(
        race_groups__class_results__in=base_results
    ).distinct().order_by('brand__name', 'type__name')

    # Применяем фильтры из GET-параметров
    results = base_results

    class_filter = request.GET.get('class')
    if class_filter:
        results = results.filter(group__race_class__id=class_filter)

    track_filter = request.GET.get('track')
    if track_filter:
        results = results.filter(group__page__track__id=track_filter)

    tyre_filter = request.GET.get('tyre')
    if tyre_filter:
        results = results.filter(group__tyre__id=tyre_filter)

    weather_filter = request.GET.get('weather')
    if weather_filter == 'dry':
        # Сухо: осадков нет или очень мало (менее 0.1 мм)
        results = results.filter(group__precipitation__lt=0.1)
    elif weather_filter == 'wet':
        # Дождь: осадки есть
        results = results.filter(group__precipitation__gte=0.1)

    temp_min = request.GET.get('temp_min')
    temp_max = request.GET.get('temp_max')
    if temp_min:
        results = results.filter(group__air_temperature__gte=float(temp_min))
    if temp_max:
        results = results.filter(group__air_temperature__lte=float(temp_max))

    # Общая статистика
    total_starts = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1,2,3]).count()
    win_percentage = round((wins / total_starts * 100), 1) if total_starts > 0 else 0
    podium_percentage = round((podiums / total_starts * 100), 1) if total_starts > 0 else 0

    # Статистика для графиков
    # 1. По температуре
    temp_stats = []
    for temp in range(-10, 41, 5):  # от -10 до +40 с шагом 5
        temp_results = results.filter(
            group__air_temperature__gte=temp,
            group__air_temperature__lt=temp+5
        )
        if temp_results.count() >= 3:  # Минимум 3 заезда для статистики
            temp_wins = temp_results.filter(position=1).count()
            temp_stats.append({
                'range': f"{temp}..{temp+5}",
                'starts': temp_results.count(),
                'win_rate': round(temp_wins / temp_results.count() * 100, 1)
            })

    # 2. По шинам
    tyre_stats = []
    for tyre in available_tyres:
        tyre_results = results.filter(group__tyre=tyre)
        if tyre_results.count() >= 3:
            tyre_wins = tyre_results.filter(position=1).count()
            tyre_stats.append({
                'tyre': {
                    'id': tyre.id,
                    'brand': {'name': tyre.brand.name},
                    'type': {'name': tyre.type.get_name_display()}
                },
                'starts': tyre_results.count(),
                'wins': tyre_wins,
                'win_rate': round(tyre_wins / tyre_results.count() * 100, 1)
            })
    tyre_stats.sort(key=lambda x: x['win_rate'], reverse=True)

    return render(request, "coderedcms/snippets/chassis_page.html", {
        "chassis": chassis,
        "object": chassis,
        "page": chassis,
        "results": results.order_by('-group__page__last_published_at'),
        "available_classes": available_classes,
        "available_tracks": available_tracks,
        "available_tyres": available_tyres,
        "temp_stats": temp_stats,
        "tyre_stats": tyre_stats,
        "total_starts": total_starts,
        "wins": wins,
        "podiums": podiums,
        "win_percentage": win_percentage,
        "podium_percentage": podium_percentage,
        "site": current_site,
    })
def tyrebrand_detail_view(request, slug):
    brand = get_object_or_404(TyreBrand, slug=slug)
    current_site = Site.find_for_request(request)

    # Получаем все шины этого производителя
    tyres = Tyre.objects.filter(brand=brand)
    print(f"Найдено шин производителя {brand.name}: {tyres.count()}")  # Отладка

    # Получаем все результаты с шинами этого производителя
    results = RaceResult.objects.filter(
        group__tyre__brand=brand
    ).select_related(
        'driver', 'team', 'group__page', 'group__race_class', 'group__tyre'
    ).order_by('-group__page__last_published_at')

    # Статистика по производителю в целом
    total_starts = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1,2,3]).count()

    # Статистика по каждому типу шин
    tyre_stats = []
    for tyre in tyres:
        tyre_results = results.filter(group__tyre=tyre)
        print(f"Шина {tyre}: найдено результатов {tyre_results.count()}")  # Отладка
        if tyre_results.exists():
            tyre_stats.append({
                'tyre': tyre,
                'starts': tyre_results.count(),
                'wins': tyre_results.filter(position=1).count(),
                'podiums': tyre_results.filter(position__in=[1,2,3]).count(),
            })

    print(f"Передаем в шаблон tyre_stats: {len(tyre_stats)}")  # Отладка

    return render(request, "coderedcms/snippets/tyrebrand_page.html", {
        "brand": brand,
        "object": brand,
        "page": brand,
        "tyres": tyres,
        "tyre_stats": tyre_stats,
        "results": results,
        "total_starts": total_starts,
        "wins": wins,
        "podiums": podiums,
        "win_percentage": round((wins/total_starts*100),1) if total_starts else 0,
        "podium_percentage": round((podiums/total_starts*100),1) if total_starts else 0,
        "site": current_site,
    })

def tyretype_detail_view(request, slug):
    tyre_type = get_object_or_404(TyreType, slug=slug)
    current_site = Site.find_for_request(request)

    results = RaceResult.objects.filter(
        group__tyre__type=tyre_type
    ).select_related(
        'driver', 'team', 'group__page', 'group__race_class', 'group__tyre'
    ).order_by('-group__page__last_published_at')

    total_starts = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1,2,3]).count()

    return render(request, "coderedcms/snippets/tyretype_page.html", {
        "tyre_type": tyre_type,
        "object": tyre_type,
        "page": tyre_type,
        "results": results,
        "total_starts": total_starts,
        "wins": wins,
        "podiums": podiums,
        "win_percentage": round((wins/total_starts*100),1) if total_starts else 0,
        "podium_percentage": round((podiums/total_starts*100),1) if total_starts else 0,
        "site": current_site,
    })

def tyre_detail_view(request, slug):
    tyre = get_object_or_404(Tyre, slug=slug)
    current_site = Site.find_for_request(request)

    results = RaceResult.objects.filter(
        group__tyre=tyre
    ).select_related(
        'driver', 'team', 'group__page', 'group__race_class'
    ).order_by('-group__page__last_published_at')

    total_starts = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1,2,3]).count()

    return render(request, "coderedcms/snippets/tyre_page.html", {
        "tyre": tyre,
        "object": tyre,
        "page": tyre,
        "results": results,
        "total_starts": total_starts,
        "wins": wins,
        "podiums": podiums,
        "win_percentage": round((wins/total_starts*100),1) if total_starts else 0,
        "podium_percentage": round((podiums/total_starts*100),1) if total_starts else 0,
        "site": current_site,
    })

def engine_detail_view(request, slug):
    engine = get_object_or_404(Engine, slug=slug)
    current_site = Site.find_for_request(request)

    # Получаем все классы для вкладок
    from website.models import RaceClass
    all_classes = RaceClass.objects.for_site()
    classes = list(all_classes)

    # Получаем выбранный класс из GET-параметров
    class_id = request.GET.get('class')
    if class_id and class_id.isdigit():
        class_id = int(class_id)
    else:
        class_id = None

    # Базовый queryset для всех результатов
    base_results = RaceResult.objects.filter(
        group__engine=engine
    ).select_related(
        'driver', 'team', 'group__page', 'group__race_class',
        'group__tyre', 'chassis_new'
    )

    # Фильтр по классу, если выбран
    if class_id:
        base_results = base_results.filter(group__race_class_id=class_id)

    # Общая статистика (без фильтра по классу - для верхней части)
    all_results = RaceResult.objects.filter(group__engine=engine)
    total_starts = all_results.count()
    wins = all_results.filter(position=1).count()
    podiums = all_results.filter(position__in=[1,2,3]).count()
    win_percentage = round((wins / total_starts * 100), 1) if total_starts > 0 else 0
    podium_percentage = round((podiums / total_starts * 100), 1) if total_starts > 0 else 0

    # Топ-10 лучших результатов (сортировка по очкам + место)
    top_results = base_results.order_by('-points', 'position')[:10]

    # Добавляем дату для каждого результата
    from website.models import EventOccurrence
    for result in top_results:
        occurrence = EventOccurrence.objects.filter(event=result.group.page).first()
        result.event_date = occurrence.end if occurrence else result.group.page.first_published_at

    context = {
        'engine': engine,
        'object': engine,
        'page': engine,
        'results': top_results,
        'total_starts': total_starts,
        'wins': wins,
        'podiums': podiums,
        'win_percentage': win_percentage,
        'podium_percentage': podium_percentage,
        'classes': classes,
        'selected_class': class_id,
        'site': current_site,
    }
    return render(request, "coderedcms/snippets/engine_page.html", context)

def compare_view(request):
    """
    Страница сравнения двух шасси с фильтрацией по классам
    """
    current_site = Site.find_for_request(request)

    # Получаем все шасси для выпадающих списков
    all_chassis = Chassis.objects.all().order_by('name')

    # Получаем все классы для вкладок
    from website.models import RaceClass
    all_classes = RaceClass.objects.for_site()
    classes = list(all_classes)

    # Получаем выбранный класс из GET-параметров
    class_id = request.GET.get('class')
    if class_id and class_id.isdigit():
        class_id = int(class_id)
    else:
        class_id = None

    # Получаем выбранные шасси
    chassis1_slug = request.GET.get('chassis1')
    chassis2_slug = request.GET.get('chassis2')

    if not chassis1_slug and request.GET.get('chassis'):
        chassis1_slug = request.GET.get('chassis')

    chassis1 = None
    chassis2 = None
    stats1 = None
    stats2 = None

    if chassis1_slug:
        chassis1 = get_object_or_404(Chassis, slug=chassis1_slug)
        stats1 = get_chassis_stats(chassis1, class_id)

    if chassis2_slug:
        chassis2 = get_object_or_404(Chassis, slug=chassis2_slug)
        stats2 = get_chassis_stats(chassis2, class_id)

    # Пары (шасси, стат, цвет) для виджета детального рейтинга
    chassis_stats_pairs = []
    if chassis1 and stats1:
        chassis_stats_pairs.append((chassis1, stats1, '#ffc107'))
    if chassis2 and stats2:
        chassis_stats_pairs.append((chassis2, stats2, '#0dcaf0'))
    if chassis_stats_pairs:
        chassis_stats_pairs.sort(key=lambda x: x[1]['win_rate'], reverse=True)

    context = {
        'all_chassis': all_chassis,
        'chassis1': chassis1,
        'chassis2': chassis2,
        'stats1': stats1,
        'stats2': stats2,
        'classes': classes,
        'selected_class': class_id,
        'chassis_stats_pairs': chassis_stats_pairs,
        'site': current_site,
        'page': None,
    }
    return render(request, "coderedcms/snippets/compare_page.html", context)
