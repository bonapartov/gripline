# website/api.py
from collections import defaultdict

from django.conf import settings
from django.core.cache import cache
from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .models import (
    ChampionshipPage, Track, RaceResult, CompetitionType,
    StagePage, EventPage, RaceClassResultGroup, RaceClass,
)
from organizers.models import Stage as OrgStage


PULSE_CACHE_KEY = 'pulse:v1:{}'


def _get_type_info(champ):
    """Возвращает (type_code, type_name) первого типа соревнования чемпионата."""
    if getattr(champ, '_pulse_type_info', None) is None:
        comp_types = list(
            champ.championship_competition_types.all()
            .select_related('competition_type')
            .values_list('competition_type__code', 'competition_type__name')
        )
        champ._pulse_type_info = comp_types[0] if comp_types else ('other', 'Серия')
    return champ._pulse_type_info


def _stages_with_events(champ):
    """
    [(StagePage, [live EventPage, …]), …] в порядке дерева — один раз на чемпионат.
    Раньше дочерние страницы каждого этапа запрашивались отдельно, и дважды
    (этапы + границы дат).
    """
    if getattr(champ, '_pulse_stages', None) is None:
        stages = [
            s for s in champ.get_children().live().filter(live=True).specific()
            if isinstance(s, StagePage)
        ]
        events_by_parent = defaultdict(list)
        for e in (EventPage.objects.live()
                  .filter(path__startswith=champ.path, depth=champ.depth + 2)
                  .order_by('path')):
            events_by_parent[e.path[:-EventPage.steplen]].append(e)
        champ._pulse_stages = [(s, events_by_parent.get(s.path, [])) for s in stages]
    return champ._pulse_stages


def _top3_by_group(event_ids):
    """
    {event_id: [(group, [RaceResult топ-3]), …]} — два запроса на все события
    вместо запроса на каждый класс каждого этапа.
    """
    groups = list(
        RaceClassResultGroup.objects.filter(page_id__in=event_ids)
        .select_related('race_class').order_by('sort_order', 'id')
    )
    top = defaultdict(list)
    for r in (
        RaceResult.objects
        .filter(group__in=groups, position__isnull=False, position__gt=0)
        .annotate(rn=Window(RowNumber(), partition_by=[F('group_id')],
                            order_by=[F('position').asc(), F('id').asc()]))
        .filter(rn__lte=3)
        .select_related('driver', 'chassis_new')
        .order_by('group_id', 'position', 'id')
    ):
        top[r.group_id].append(r)
    by_event = defaultdict(list)
    for g in groups:
        by_event[g.page_id].append((g, top[g.id]))
    return by_event


def _get_champ_date_bounds(champ, draft_ids):
    """Реальные даты первого и последнего этапа по всему чемпионату (без year_filter)."""
    dates = []
    for stage, live_events in _stages_with_events(champ):
        if stage.id in draft_ids:
            continue
        if not stage.start_date:
            continue
        if not live_events:
            continue
        dates.append((stage.start_date, stage.end_date))
    if not dates:
        return None, None
    dates.sort(key=lambda x: x[0])
    date_first = dates[0][0].strftime('%d.%m')
    last_end = dates[-1][1] or dates[-1][0]
    date_last_full = last_end.strftime('%d.%m.%Y')
    return date_first, date_last_full


def _collect_stages(champ, year_filter, draft_ids, track_ids_used, track_stage_count):
    """
    Собирает данные этапов для одного чемпионата.
    Возвращает (stages_list, event_ids_list).
    year_filter=None означает «показывать все годы».
    """
    type_code, type_name = _get_type_info(champ)
    stages = []
    event_ids = []

    selected = [
        (stage, live_events) for stage, live_events in _stages_with_events(champ)
        if stage.id not in draft_ids and stage.start_date
        and not (year_filter and stage.start_date.year != year_filter)
    ]
    top3 = _top3_by_group([e.id for _, live_events in selected for e in live_events])

    for stage, live_events in selected:
        # Трасса
        track_info = None
        if stage.track:
            t = stage.track
            track_info = {'id': t.id, 'name': t.name, 'city': t.city or ''}
            track_ids_used.add(t.id)
            track_stage_count[t.id] = track_stage_count.get(t.id, 0) + 1

        # Обложка: сначала своя, потом обложка чемпионата как фоллбэк
        cover_url = None
        if getattr(stage, 'cover_image', None):
            try:
                cover_url = stage.cover_image.get_rendition('fill-118x80').url
            except Exception:
                pass
        if not cover_url and getattr(champ, 'cover_image', None):
            try:
                cover_url = champ.cover_image.get_rendition('fill-118x80').url
            except Exception:
                pass

        # Только этапы с live EventPage-детьми
        if not live_events:
            continue

        # Победители по классам (топ-3)
        winners = []
        first_event_url = None
        for event in live_events:
            if first_event_url is None:
                first_event_url = event.url
            event_ids.append(event.id)
            for group, group_top3 in top3[event.id]:
                places = [
                    {
                        'position': r.position,
                        'name': r.driver.full_name if r.driver else '—',
                        'driver_url': r.driver.get_absolute_url() if r.driver else '',
                        'race_number': r.race_number or '',
                        'chassis': r.chassis_new.name if r.chassis_new else '',
                    }
                    for r in group_top3
                ]
                if places:
                    winners.append({
                        'class_id': group.race_class_id,
                        'class_name': group.race_class.name if group.race_class else '',
                        'event_url': event.url,
                        'places': places,
                    })

        stages.append({
            'id': stage.id,
            'title': stage.title,
            'url': first_event_url or stage.url,
            'date_start': stage.start_date.strftime('%d.%m'),
            'date_end': stage.end_date.strftime('%d.%m') if stage.end_date else '',
            'date_end_full': stage.end_date.strftime('%d.%m.%Y') if stage.end_date else '',
            'date_iso': stage.start_date.isoformat(),
            '_sort': stage.start_date.isoformat(),
            'track': track_info,
            'cover_image': cover_url,
            'championship_id': champ.id,
            'championship_title': champ.title,
            'championship_url': champ.url,
            'type_code': type_code,
            'type_name': type_name,
            'winners': winners,
        })

    return stages, event_ids


def _pulse_cache_enabled():
    # Как wagtailcache: в dev.py кэш выключен, правки видны сразу
    return getattr(settings, 'WAGTAIL_CACHE', True)


def clear_pulse_cache():
    """Сбросить кэш Пульса. Публикация страниц в админке и clear_wagtail_cache
    чистят его и так (общий кэш default) — это для остальных случаев."""
    years = {None} | set(range(2000, 2101))
    cache.delete_many([PULSE_CACHE_KEY.format(y or 'all') for y in years])


def rebuild_pulse_cache():
    """Пересобрать кэш Пульса за все годы — из update_all_analytics."""
    clear_pulse_cache()
    if not _pulse_cache_enabled():
        return 0
    payload = _build_pulse_payload(None)
    cache.set(PULSE_CACHE_KEY.format('all'), JsonResponse(payload).content)
    for y in payload['filters']['years']:
        cache.set(PULSE_CACHE_KEY.format(y), JsonResponse(_build_pulse_payload(y)).content)
    return 1 + len(payload['filters']['years'])


@require_GET
@csrf_exempt
def pulse_data(request):
    year_param = request.GET.get('year')
    year = int(year_param) if year_param else None
    # Результаты меняются только при вводе данных — отдаём готовый JSON.
    # Чужие годы не кэшируем, чтобы перебором ?year= не плодить файлы.
    if not _pulse_cache_enabled() or not (year is None or 2000 <= year <= 2100):
        return JsonResponse(_build_pulse_payload(year))
    key = PULSE_CACHE_KEY.format(year or 'all')
    content = cache.get(key)
    if content is None:
        content = JsonResponse(_build_pulse_payload(year)).content
        cache.set(key, content)
    return HttpResponse(content, content_type='application/json')


def _build_pulse_payload(year):
    from datetime import date as _date
    calendar_year = _date.today().year

    all_champs = ChampionshipPage.objects.live().public().specific()

    # ID страниц этапов, скрытых организатором (черновик)
    _draft_stage_ids = set(
        OrgStage.objects.filter(is_published=False, wagtail_page__isnull=False)
        .values_list('wagtail_page_id', flat=True)
    )

    # Текущие чемпионаты (по году)
    if year:
        current_champs = [c for c in all_champs if year in c.get_years()]
    else:
        current_champs = list(all_champs)

    current_champ_ids = {c.id for c in current_champs}

    # ── Строим данные лидеров и этапы для текущих чемпионатов ─────────────
    championships_data = []
    all_stages = []
    track_ids_used = set()
    track_stage_count = {}
    champ_event_ids = {}

    for champ in current_champs:
        type_code, type_name = _get_type_info(champ)

        # Сезон через Новый год (зимний кубок: ноябрь–январь) показывается целиком
        # в каждом своём году — и таблица, и этапы, не только этапы этого года
        champions_by_class = champ.get_champions_by_class()
        title_prefix = 'Чемпионы' if champ.is_completed else 'Лидеры'

        champions_display = []
        for class_id, class_data in champions_by_class.items():
            for champ_data in class_data['champions']:
                photo_url = None
                if champ_data['driver'].photo:
                    try:
                        photo_url = champ_data['driver'].photo.get_rendition('fill-150x150').url
                    except Exception:
                        pass
                champions_display.append({
                    'class': class_data['name'],
                    'class_id': class_id,
                    'position': champ_data['position'],
                    '_driver_id': champ_data['driver'].id,
                    'name': champ_data['driver'].full_name,
                    'photo': photo_url,
                    'points': champ_data['points'],
                    'url': champ_data['driver'].get_absolute_url(),
                    'race_number': '',
                })

        cover_url = None
        if getattr(champ, 'cover_image', None):
            try:
                cover_url = champ.cover_image.get_rendition('fill-800x533').url
            except Exception:
                pass

        championships_data.append({
            'id': champ.id,
            'title': champ.title,
            'years': champ.get_years(),
            'type': type_name,
            'type_code': type_code,
            'is_completed': champ.is_completed,
            'is_current': calendar_year in champ.get_years(),
            'title_prefix': title_prefix,
            'url': champ.url,
            'champions': champions_display,
            'cover_image': cover_url,
        })

        stages, event_ids = _collect_stages(
            champ, None, _draft_stage_ids, track_ids_used, track_stage_count
        )
        all_stages.extend(stages)
        champ_event_ids[champ.id] = event_ids

    # ── Группировка и сортировка ───────────────────────────────────────────
    # Внутри каждого чемпионата — новейшие первые.
    # Порядок групп: по убыванию даты последнего этапа. Чемпионаты других лет
    # (раньше — «предыдущий завершённый») не показываются: сезон через Новый
    # год и так виден целиком в каждом своём году.
    stages_by_champ = defaultdict(list)
    for s in all_stages:
        stages_by_champ[s['championship_id']].append(s)

    for cid in stages_by_champ:
        stages_by_champ[cid].sort(key=lambda s: s['_sort'], reverse=True)

    ordered_champ_ids = sorted(
        stages_by_champ,
        key=lambda cid: max(s['_sort'] for s in stages_by_champ[cid]),
        reverse=True,
    )

    # Плоский список для клиентских фильтров
    all_stages = []
    for cid in ordered_champ_ids:
        all_stages.extend(stages_by_champ[cid])

    # Метаданные групп для рендера СТАРТ/ФИНИШ в JS
    champ_map = {c.id: c for c in list(all_champs)}
    stage_groups = []
    for cid in ordered_champ_ids:
        group_stages = stages_by_champ[cid]
        champ_page = champ_map.get(cid)
        if not champ_page:
            continue
        type_code, type_name = _get_type_info(champ_page)
        champ_date_first, champ_date_last_full = _get_champ_date_bounds(champ_page, _draft_stage_ids)
        stage_groups.append({
            'id': cid,
            'title': champ_page.title,
            'type_code': type_code,
            'type_name': type_name,
            'is_completed': champ_page.is_completed,
            'is_current': cid in current_champ_ids,
            'date_first': champ_date_first,
            'date_last_full': champ_date_last_full,
        })

    # Удаляем служебный ключ сортировки
    for s in all_stages:
        del s['_sort']

    # ── race_number для лидеров ────────────────────────────────────────────
    for champ_obj, champ_d in zip(current_champs, championships_data):
        event_ids = champ_event_ids.get(champ_obj.id, [])
        if not event_ids:
            continue
        driver_ids = [c['_driver_id'] for c in champ_d['champions']]
        if not driver_ids:
            continue

        seen = {}
        for r in (
            RaceResult.objects
            .filter(driver_id__in=driver_ids, group__page_id__in=event_ids)
            .exclude(race_number__isnull=True).exclude(race_number='')
            .order_by('driver_id', '-id')
            .values('driver_id', 'race_number')
        ):
            if r['driver_id'] not in seen:
                seen[r['driver_id']] = r['race_number']

        for c in champ_d['champions']:
            c['race_number'] = seen.get(c['_driver_id'], '')
            del c['_driver_id']
            del c['class_id']

    # ── Трассы ────────────────────────────────────────────────────────────
    tracks_data = []
    for t in Track.objects.filter(id__in=track_ids_used):
        if t.latitude and t.longitude:
            tracks_data.append({
                'id': t.id,
                'name': t.name,
                'city': t.city or '',
                'lat': float(t.latitude),
                'lng': float(t.longitude),
                'stage_count': track_stage_count.get(t.id, 0),
            })

    # ── Фильтры ───────────────────────────────────────────────────────────
    all_years = set()
    for champ in all_champs:
        all_years.update(champ.get_years())

    type_names_in_year = sorted(set(
        name
        for champ in current_champs
        for name in champ.championship_competition_types.all()
                        .values_list('competition_type__name', flat=True)
    ))

    return {
        'championships': championships_data,
        'stages': all_stages,
        'stage_groups': stage_groups,
        'tracks': tracks_data,
        'filters': {
            'years': sorted(list(all_years), reverse=True),
            'types': type_names_in_year,
            # {название класса: порядок} — чипы классов на /pulse/ (pulse.js)
            # сортируются по этому порядку вместо localeCompare, тот же
            # источник, что и RaceClass.sort_order по всему остальному сайту.
            'class_order': dict(RaceClass.objects.values_list('name', 'sort_order')),
        },
    }
