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
    types = request.GET.getlist('type')  # Множественный выбор
    classes = request.GET.getlist('class')  # Множественный выбор

    # Получаем все чемпионаты
    champs = ChampionshipPage.objects.live().public().specific()

    # Фильтр по году
    if year:
        year = int(year)
        filtered_champs = []
        for champ in champs:
            champ_years = champ.get_years()
            if year in champ_years:
                filtered_champs.append(champ)
        champs = filtered_champs

    # Фильтр по типу соревнований (обновлён для ManyToMany)
    if types:
        filtered_champs = []
        for champ in champs:
            # ИСПРАВЛЕНО: используем championship_competition_types
            champ_types = list(champ.championship_competition_types.all().values_list('competition_type__code', flat=True))
            if set(types) & set(champ_types):
                filtered_champs.append(champ)
        champs = filtered_champs

    # Фильтр по классам
    if classes:
        filtered_champs = []
        for champ in champs:
            events = champ.get_children().live().specific()
            # Получаем классы, которые есть в этом чемпионате
            champ_classes = set(RaceResult.objects.filter(
                group__page__in=events
            ).values_list('group__race_class__name', flat=True).distinct())

            # Проверяем, есть ли пересечение с выбранными классами
            if set(classes) & champ_classes:
                filtered_champs.append(champ)
        champs = filtered_champs

    # Собираем данные
    data = []
    track_ids = set()

    for champ in champs:
        # Получаем годы чемпионата
        champ_years = champ.get_years()

        # Получаем чемпионов по классам с учётом года и статуса завершённости
        if champ.is_completed and year and int(year) == champ.get_years()[-1]:
            # Завершённый чемпионат И выбран последний год → чемпионы (все этапы)
            champions_by_class = champ.get_champions_by_class()
            title_prefix = "Чемпионы"
        else:
            # Иначе — лидеры только за выбранный год
            champions_by_class = champ.get_champions_by_class(year=int(year) if year else None)
            title_prefix = "Лидеры"

        # Формируем данные для отображения
        champions_display = []
        for class_id, class_data in champions_by_class.items():
            for champ_data in class_data['champions']:
                photo_url = None
                if champ_data['driver'].photo:
                    photo_url = champ_data['driver'].photo.get_rendition('fill-150x150').url

                champions_display.append({
                    'class': class_data['name'],
                    'position': champ_data['position'],
                    'name': champ_data['driver'].full_name,
                    'photo': photo_url,
                    'points': champ_data['points'],
                    'url': champ_data['driver'].get_absolute_url(),
                })

        # Получаем обложку
        cover_url = None
        if hasattr(champ, 'cover_image') and champ.cover_image:
            cover_url = champ.cover_image.get_rendition('fill-800x533').url

        # Получаем типы соревнований через связанную модель ChampionshipCompetitionType
        # ИСПРАВЛЕНО: обе строки используют championship_competition_types
        raw_types = list(champ.championship_competition_types.all().values_list('competition_type__code', flat=True))
        display_types = list(champ.championship_competition_types.all().values_list('competition_type__name', flat=True))

        champ_data = {
            'id': champ.id,
            'title': champ.title,
            'years': champ_years,
            'primary_year': champ_years[0] if champ_years else None,
            'type': display_types,  # Для отображения: ["Кубок", "Чемпионат"]
            'type_raw': raw_types,  # Для фильтрации: ["cup", "championship"]
            'is_completed': champ.is_completed,
            'title_prefix': title_prefix,
            'url': champ.url,
            'champions': champions_display,
            'cover_image': cover_url,
        }

        # Получаем трассы из дочерних событий
        events = champ.get_children().live().specific()
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

        champ_data['tracks'] = champ_tracks

        # Получаем классы из результатов
        class_ids = RaceResult.objects.filter(
            group__page__in=events
        ).values_list('group__race_class_id', flat=True).distinct()

        champ_data['classes'] = list(RaceClass.objects.filter(
            id__in=class_ids
        ).values('id', 'name'))

        data.append(champ_data)

    # Получаем все задействованные трассы
    tracks = Track.objects.filter(id__in=track_ids)
    tracks_data = [{
        'id': t.id,
        'name': t.name,
        'region': t.region,
        'city': t.city,
        'lat': float(t.latitude) if t.latitude else None,
        'lng': float(t.longitude) if t.longitude else None,
        'url': t.get_absolute_url(),
    } for t in tracks if t.latitude and t.longitude]

    # Получаем все уникальные годы из всех чемпионатов
    all_years = set()
    for champ in ChampionshipPage.objects.live().public().specific():
        all_years.update(champ.get_years())

    # Получаем все уникальные типы из всех чемпионатов
    all_types = set()
    for champ in ChampionshipPage.objects.live().public():
        # ИСПРАВЛЕНО: используем championship_competition_types
        champ_types = list(champ.championship_competition_types.all().values_list('competition_type__code', flat=True))
        all_types.update(champ_types)

    available_types = list(all_types)

    # Получаем все объекты CompetitionType для преобразования в названия
    competition_types = CompetitionType.objects.filter(code__in=available_types)
    type_map = {ct.code: ct.name for ct in competition_types}
    available_types_display = [type_map.get(t, t) for t in available_types]

    return JsonResponse({
        'championships': data,
        'tracks': tracks_data,
        'filters': {
            'years': sorted(list(all_years), reverse=True),
            'types': list(available_types_display),
            'types_raw': list(available_types),
        }
    })
