# website/api.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from .models import ChampionshipPage, Track, RaceClass, RaceResult, CompetitionType
from wagtail.models import Page


@require_GET
@csrf_exempt
def pulse_data(request):
    """
    API для получения данных Пульса
    """
    year = request.GET.get('year')
    types = request.GET.getlist('type')
    classes = request.GET.getlist('class')

    # Загружаем все чемпионаты разом с prefetch типов соревнований
    all_champs = list(
        ChampionshipPage.objects.live().public()
        .prefetch_related('championship_competition_types__competition_type')
        .specific()
    )

    # Кэшируем get_years() и события для каждого чемпионата — чтобы не дёргать БД повторно
    champ_years_cache = {}
    champ_events_cache = {}
    for champ in all_champs:
        champ_years_cache[champ.id] = champ.get_years()
        champ_events_cache[champ.id] = list(champ.get_children().live().specific())

    # Собираем all_years и all_types из кэша (без повторных запросов в конце)
    all_years = set()
    all_types_map = {}  # code → name
    for champ in all_champs:
        all_years.update(champ_years_cache[champ.id])
        for ct in champ.championship_competition_types.all():
            all_types_map[ct.competition_type.code] = ct.competition_type.name

    # Фильтрация
    if year:
        year = int(year)
    champs = all_champs

    if year:
        champs = [c for c in champs if year in champ_years_cache[c.id]]

    if types:
        champs = [
            c for c in champs
            if set(types) & {ct.competition_type.code for ct in c.championship_competition_types.all()}
        ]

    if classes:
        filtered = []
        for champ in champs:
            events = champ_events_cache[champ.id]
            champ_classes = set(
                RaceResult.objects.filter(group__page__in=events)
                .values_list('group__race_class__name', flat=True)
                .distinct()
            )
            if set(classes) & champ_classes:
                filtered.append(champ)
        champs = filtered

    # Собираем данные
    data = []
    track_ids = set()

    for champ in champs:
        champ_years = champ_years_cache[champ.id]
        events = champ_events_cache[champ.id]

        # Определяем режим: чемпионы или лидеры
        if champ.is_completed and year and champ_years and year == champ_years[-1]:
            champions_by_class = champ.get_champions_by_class()
            title_prefix = "Чемпионы"
        else:
            champions_by_class = champ.get_champions_by_class(year=year)
            title_prefix = "Лидеры"

        champions_display = []
        for class_id, class_data in champions_by_class.items():
            for entry in class_data['champions']:
                driver = entry['driver']
                photo_url = None
                if driver.photo_id:
                    try:
                        photo_url = driver.photo.get_rendition('fill-150x150').url
                    except Exception:
                        pass
                champions_display.append({
                    'class': class_data['name'],
                    'position': entry['position'],
                    'name': driver.full_name,
                    'photo': photo_url,
                    'points': entry['points'],
                    'url': driver.get_absolute_url(),
                })

        cover_url = None
        if hasattr(champ, 'cover_image') and champ.cover_image:
            try:
                cover_url = champ.cover_image.get_rendition('fill-800x533').url
            except Exception:
                pass

        raw_types = [ct.competition_type.code for ct in champ.championship_competition_types.all()]
        display_types = [ct.competition_type.name for ct in champ.championship_competition_types.all()]

        champ_tracks = []
        for event in events:
            if hasattr(event, 'track') and event.track:
                champ_tracks.append({
                    'id': event.track.id,
                    'name': event.track.name,
                    'region': event.track.region,
                    'city': event.track.city,
                    'lat': float(event.track.latitude) if event.track.latitude else None,
                    'lng': float(event.track.longitude) if event.track.longitude else None,
                })
                track_ids.add(event.track.id)

        class_ids = (
            RaceResult.objects.filter(group__page__in=events)
            .values_list('group__race_class_id', flat=True)
            .distinct()
        )

        data.append({
            'id': champ.id,
            'title': champ.title,
            'years': champ_years,
            'primary_year': champ_years[0] if champ_years else None,
            'type': display_types,
            'type_raw': raw_types,
            'is_completed': champ.is_completed,
            'title_prefix': title_prefix,
            'url': champ.url,
            'champions': champions_display,
            'cover_image': cover_url,
            'tracks': champ_tracks,
            'classes': list(RaceClass.objects.filter(id__in=class_ids).values('id', 'name')),
        })

    tracks = Track.objects.filter(id__in=track_ids)
    tracks_data = [
        {
            'id': t.id,
            'name': t.name,
            'region': t.region,
            'city': t.city,
            'lat': float(t.latitude) if t.latitude else None,
            'lng': float(t.longitude) if t.longitude else None,
            'url': t.get_absolute_url(),
        }
        for t in tracks if t.latitude and t.longitude
    ]

    available_types = list(all_types_map.keys())
    available_types_display = [all_types_map[t] for t in available_types]

    return JsonResponse({
        'championships': data,
        'tracks': tracks_data,
        'filters': {
            'years': sorted(all_years, reverse=True),
            'types': available_types_display,
            'types_raw': available_types,
        }
    })
