from django.shortcuts import render, get_object_or_404
from django.urls import path
from wagtail.snippets.views.snippets import SnippetViewSet
from website.models import Driver, Team, RaceResult, Track, Chassis, TyreBrand, TyreType, Tyre, Engine
from django.utils.timezone import now
# Добавляем импорт для определения текущего сайта (нужно для Header/Footer)
from wagtail.models import Site
from django.db.models import F, OuterRef, Subquery, Avg
from .models import EventOccurrence
from django.db import models
from django.utils import timezone
import zoneinfo
from .models import AnalyticsMetadata
from datetime import timedelta
from django.db.models import Max
from .models import TeamStaff, TeamStaffMembership
from django.http import JsonResponse


# Классы для админки (Wagtail Snippets)
class DriverViewSet(SnippetViewSet):
    model = Driver
    icon = "user"
    menu_label = "Пилоты"
    menu_name = "drivers_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", driver_detail_view, name="details"),
        ]

class TeamViewSet(SnippetViewSet):
    model = Team
    icon = "group"
    menu_label = "Команды"
    menu_name = "teams_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", team_detail_view, name="details"),
        ]
class TrackViewSet(SnippetViewSet):
    model = Track
    icon = "site"  # Иконка для админки
    menu_label = "Трассы"
    menu_name = "tracks_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", track_detail_view, name="details"),
        ]
class ChassisViewSet(SnippetViewSet):
    model = Chassis
    icon = "cog"
    menu_label = "Шасси"
    menu_name = "chassis_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", chassis_detail_view, name="details"),
        ]

class TyreBrandViewSet(SnippetViewSet):
    model = TyreBrand
    icon = "fa-brands"
    menu_label = "Производители шин"
    menu_name = "tyrebrand_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", tyrebrand_detail_view, name="details"),
        ]

class TyreTypeViewSet(SnippetViewSet):
    model = TyreType
    icon = "fa-type"
    menu_label = "Типы шин"
    menu_name = "tyretype_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", tyretype_detail_view, name="details"),
        ]

class TyreViewSet(SnippetViewSet):
    model = Tyre
    icon = "fa-tyre"
    menu_label = "Шины"
    menu_name = "tyre_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", tyre_detail_view, name="details"),
        ]

class EngineViewSet(SnippetViewSet):
    model = Engine
    icon = "fa-engine"
    menu_label = "Двигатели"
    menu_name = "engine_snippet"
    add_to_admin_menu = False

    def get_urlpatterns(self):
        return super().get_urlpatterns() + [
            path("<slug:slug>/", engine_detail_view, name="details"),
        ]

# Функции для отображения на сайте
def driver_detail_view(request, slug):
    driver = get_object_or_404(Driver, slug=slug)

    # Пытаемся найти текущий сайт, чтобы CMS могла подтянуть верное меню
    current_site = Site.find_for_request(request)

    # Получаем дату окончания для каждого этапа
    results = RaceResult.objects.filter(driver=driver).select_related(
        'group__page',
        'group__race_class',
        'team'
    ).annotate(
        event_date=Subquery(
            EventOccurrence.objects.filter(
                event_id=OuterRef('group__page_id')
            ).order_by('-end').values('end')[:1]
        )
    ).order_by('-event_date', '-group__page__last_published_at')

    # --- РАСЧЕТ СТАТИСТИКИ ---
    total_starts = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1,2,3]).count()

    # Расчет процентов (защита от деления на ноль)
    win_percentage = round((wins / total_starts * 100), 1) if total_starts > 0 else 0
    podium_percentage = round((podiums / total_starts * 100), 1) if total_starts > 0 else 0
    # -------------------------
    # Получаем дату последнего глобального обновления
    last_update = None
    try:
        last_update_utc = AnalyticsMetadata.objects.get(key='last_updated').value
        # Преобразуем в московское время
        moscow_tz = zoneinfo.ZoneInfo('Europe/Moscow')
        last_update = last_update_utc.astimezone(moscow_tz)
    except AnalyticsMetadata.DoesNotExist:
        pass

    # Получаем рейтинги из by_class (берём первый попавшийся класс)
    pagerank_value = 0
    ensemble_value = 0
    context_value = 0

    if driver.pagerank_by_class:
        first_class = list(driver.pagerank_by_class.values())[0]
        pagerank_value = first_class.get('score', 0)

    if driver.ensemble_by_class:
        first_class = list(driver.ensemble_by_class.values())[0]
        ensemble_value = first_class.get('score', 0)

    if driver.context_by_class:
        first_class = list(driver.context_by_class.values())[0]
        context_value = first_class.get('score', 0)

    return render(request, "coderedcms/snippets/driver_page.html", {
        "driver": driver,
        "object": driver,
        # ВАЖНО: CodeRedCMS ищет переменную 'page' для вывода Header и Footer
        "page": driver,
        "results": results,
        # Передаем сайт, чтобы ссылки в меню работали корректно
        "site": current_site,
        # --- НОВЫЕ ПЕРЕМЕННЫЕ ДЛЯ СТАТИСТИКИ ---
        "total_starts": total_starts,
        "wins": wins,
        "podiums": podiums,
        "win_percentage": win_percentage,
        "podium_percentage": podium_percentage,
        # -------------------------------------
        "rating_score": driver.rating_score,
        "pagerank_score": pagerank_value,
        "ensemble_score": ensemble_value,
        "context_score": context_value,
        "last_update": last_update,
    })

def team_detail_view(request, slug):
    team = get_object_or_404(Team, slug=slug)
    current_site = Site.find_for_request(request)

    # Получаем всех пилотов команды (только активных)
    team_drivers = Driver.objects.filter(
        team_memberships__team=team,
        team_memberships__is_active=True
    ).distinct()

    # Создаем список для отображения с классами
    driver_classes = []
    six_months_ago = timezone.now() - timedelta(days=180)

    for driver in team_drivers:
        classes_with_dates = RaceResult.objects.filter(
            team=team,
            driver=driver,
            group__page__last_published_at__gte=six_months_ago
        ).values('group__race_class__name').annotate(
            last_date=Max('group__page__last_published_at')
        ).order_by('-last_date')

        for item in classes_with_dates:
            driver_classes.append({
                'driver': driver,
                'class_name': item['group__race_class__name'],
            })

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

    return render(request, "coderedcms/snippets/team_page.html", {
        "team": team,
        "driver_classes": driver_classes,
        "staff_members": staff_list,
        "site": current_site,
    })

def track_detail_view(request, slug):
    track = get_object_or_404(Track, slug=slug)
    current_site = Site.find_for_request(request)

    from .models import EventPage, EventOccurrence
    from django.db.models import OuterRef, Subquery
    from django.utils import timezone
    import sys  # для вывода в консоль

    # Получаем все события на этой трассе с аннотацией даты
    all_events = EventPage.objects.live().filter(track=track).distinct().annotate(
        event_date=Subquery(
            EventOccurrence.objects.filter(
                event_id=OuterRef('id')
            ).order_by('-start').values('start')[:1]
        )
    )

    # ОТЛАДКА
    print(f"\n=== ТРАССА: {track.name} ===", file=sys.stderr)
    print(f"Всего событий на трассе: {all_events.count()}", file=sys.stderr)

    # Текущая дата и время
    now = timezone.now()
    print(f"Текущее время: {now}", file=sys.stderr)

    # Разделяем на прошедшие и предстоящие
    past_events = []
    upcoming_events = []

    for event in all_events:
        occurrence = event.occurrences.first()

        # Определяем дату события
        if occurrence and occurrence.end:
            event_datetime = occurrence.end
            date_source = "end"
        elif occurrence and occurrence.start:
            event_datetime = occurrence.start
            date_source = "start"
        else:
            event_datetime = event.first_published_at
            date_source = "first_published_at"

        # Сравниваем с текущим моментом
        is_past = event_datetime < now

        print(f"  Событие: {event.title}", file=sys.stderr)
        print(f"    Дата ({date_source}): {event_datetime}", file=sys.stderr)
        print(f"    Прошедшее: {is_past}", file=sys.stderr)

        if is_past:
            past_events.append(event)
        else:
            upcoming_events.append(event)

    print(f"Прошедших: {len(past_events)}", file=sys.stderr)
    print(f"Предстоящих: {len(upcoming_events)}", file=sys.stderr)

    # Сортируем
    past_events.sort(key=lambda x: x.event_date or x.first_published_at, reverse=True)
    upcoming_events.sort(key=lambda x: x.event_date or x.first_published_at)

    return render(request, "coderedcms/snippets/track_page.html", {
        "track": track,
        "object": track,
        "page": track,
        "past_events": past_events,
        "upcoming_events": upcoming_events,
        "site": current_site,
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
    from .models import RaceClass, Track, Tyre

    available_classes = RaceClass.objects.filter(
        raceclassresultgroup__class_results__in=base_results
    ).distinct().order_by('name')

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
    from .models import RaceClass
    all_classes = RaceClass.objects.all()

    # Сортируем классы в нужном порядке
    class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                   'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 Masters']
    classes = sorted(all_classes,
                     key=lambda x: class_order.index(x.name) if x.name in class_order else 999)

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
    from .models import EventOccurrence
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
    from .models import RaceClass
    all_classes = RaceClass.objects.all()

    # Сортируем классы в нужном порядке
    class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                   'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 Masters']
    classes = sorted(all_classes,
                     key=lambda x: class_order.index(x.name) if x.name in class_order else 999)

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

    context = {
        'all_chassis': all_chassis,
        'chassis1': chassis1,
        'chassis2': chassis2,
        'stats1': stats1,
        'stats2': stats2,
        'classes': classes,
        'selected_class': class_id,
        'site': current_site,
        'page': None,
    }
    return render(request, "coderedcms/snippets/compare_page.html", context)


def get_chassis_stats(chassis, class_id=None):
    """Вспомогательная функция для получения статистики шасси с фильтром по классу"""
    from django.db.models import Q

    # Базовый queryset
    results = RaceResult.objects.filter(chassis_new=chassis)

    # Фильтр по классу, если указан
    if class_id:
        results = results.filter(group__race_class_id=class_id)

    total = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1,2,3]).count()

    # Статистика по погоде
    dry_results = results.filter(group__precipitation__lt=0.1)
    wet_results = results.filter(group__precipitation__gte=0.1)

    return {
        'total': total,
        'wins': wins,
        'podiums': podiums,
        'win_rate': round(wins/total*100, 1) if total else 0,
        'podium_rate': round(podiums/total*100, 1) if total else 0,
        'dry_wins': dry_results.filter(position=1).count(),
        'dry_total': dry_results.count(),
        'wet_wins': wet_results.filter(position=1).count(),
        'wet_total': wet_results.count(),
        'avg_position': round(results.aggregate(avg=Avg('position'))['avg'] or 0, 2),
    }
def top_drivers_view(request):
    """
    Страница с топ-пилотами (главный рейтинг - Ансамбль)
    """
    current_site = Site.find_for_request(request)

    from .models import Driver, RaceClass, RaceResult

    # Получаем все классы для вкладок
    class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                   'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 32+']
    all_classes = list(RaceClass.objects.all())
    classes = sorted(all_classes, key=lambda x: class_order.index(x.name) if x.name in class_order else 999)

    # Получаем выбранный класс
    selected_class_id = request.GET.get('class')
    if selected_class_id and selected_class_id.isdigit():
        selected_class_id = int(selected_class_id)
    else:
        selected_class_id = classes[0].id if classes else None

    # Получаем пилотов с рейтингом ансамбля
    drivers = Driver.objects.exclude(ensemble_by_class={}).order_by('last_name')

    result_drivers = []

    for driver in drivers:
        if selected_class_id:
            class_key = str(selected_class_id)
            ensemble_data = driver.ensemble_by_class.get(class_key, {})

            if not ensemble_data:
                continue

            rating_score = ensemble_data.get('score', 0)
            starts = ensemble_data.get('starts', 0)

            # Статистика
            results = RaceResult.objects.filter(
                driver=driver,
                group__race_class_id=selected_class_id
            )
            race_count = results.count()
            win_count = results.filter(position=1).count()
            podium_count = results.filter(position__in=[1,2,3]).count()
            win_percentage = round(win_count / race_count * 100, 1) if race_count > 0 else 0

            driver.race_count = race_count
            driver.win_count = win_count
            driver.podium_count = podium_count
            driver.win_percentage = win_percentage
            driver.rating_score = rating_score
            driver.starts_in_class = starts

            result_drivers.append(driver)

    # Сортируем по рейтингу
    result_drivers.sort(key=lambda x: x.rating_score, reverse=True)

    # Добавляем место
    for idx, driver in enumerate(result_drivers, 1):
        driver.rank = idx

    # Нормируем
    if result_drivers:
        min_rating = result_drivers[-1].rating_score
        max_rating = result_drivers[0].rating_score
        rating_range = max_rating - min_rating if max_rating > min_rating else 1

        for driver in result_drivers:
            driver.normalized_rating = round(
                (driver.rating_score - min_rating) / rating_range * 100, 1
            )

    return render(request, "coderedcms/snippets/top_drivers_page.html", {
        "drivers": result_drivers,
        "classes": classes,
        "selected_class_id": selected_class_id,
        "site": current_site,
        "page": None,
    })


def compare_drivers_view(request):
    """
    Страница сравнения двух пилотов
    """
    current_site = Site.find_for_request(request)

    # Получаем ID пилотов из GET-параметров
    driver1_id = request.GET.get('driver1')
    driver2_id = request.GET.get('driver2')

    # Получаем выбранный класс для фильтрации
    class_id = request.GET.get('class')
    if class_id and class_id.isdigit():
        class_id = int(class_id)
    else:
        class_id = None

    # Получаем все классы для кнопок
    from .models import RaceClass
    all_classes = RaceClass.objects.all().order_by('name')

    # Формируем список классов в нужном порядке
    class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                   'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 Masters']
    classes = sorted(all_classes,
                     key=lambda x: class_order.index(x.name) if x.name in class_order else 999)

    # Получаем всех пилотов
    all_drivers = Driver.objects.all().order_by('last_name', 'first_name')

    # Фильтруем пилотов по классу, если выбран класс
    filtered_drivers = all_drivers
    if class_id:
        # Оставляем только пилотов, у которых есть гонки в этом классе
        from django.db.models import Count
        driver_ids = RaceResult.objects.filter(
            group__race_class_id=class_id
        ).values('driver_id').annotate(
            count=Count('id')
        ).filter(count__gt=0).values_list('driver_id', flat=True)

        filtered_drivers = all_drivers.filter(id__in=driver_ids)
        print(f"🔍 Выбран класс {class_id}, найдено пилотов: {filtered_drivers.count()}")

    # Загружаем пилотов
    driver1 = None
    driver2 = None
    stats1 = None
    stats2 = None

    if driver1_id and driver1_id.isdigit():
        driver1 = get_object_or_404(Driver, id=int(driver1_id))

    if driver2_id and driver2_id.isdigit():
        driver2 = get_object_or_404(Driver, id=int(driver2_id))

    # Считаем статистику
    if driver1:
        stats1 = get_driver_stats(driver1, class_id, all_drivers, driver2)

    if driver2:
        stats2 = get_driver_stats(driver2, class_id, all_drivers, driver1)

    context = {
        'driver1': driver1,
        'driver2': driver2,
        'stats1': stats1,
        'stats2': stats2,
        'classes': classes,
        'selected_class': class_id,
        'all_drivers': filtered_drivers,  # ← Отправляем отфильтрованный список
        'site': current_site,
        'page': None,
    }
    return render(request, "coderedcms/snippets/compare_drivers.html", context)

def get_driver_stats(driver, class_id=None, all_drivers=None, other_driver=None):
    """
    Вспомогательная функция для получения статистики пилота
    """
    from django.db.models import Count, Avg, Q, Min
    from .models import RaceResult, EventOccurrence

    # Базовый queryset
    results = RaceResult.objects.filter(driver=driver)

    # Фильтр по классу, если указан
    if class_id:
        results = results.filter(group__race_class_id=class_id)

    # Общая статистика
    total_starts = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1,2,3]).count()

    # Статистика по классам
    class_stats = []
    class_results = results.values('group__race_class__name').annotate(
        starts=Count('id'),
        wins=Count('id', filter=Q(position=1)),
        podiums=Count('id', filter=Q(position__in=[1,2,3]))
    ).order_by('-starts')

    for stat in class_results:
        class_stats.append({
            'name': stat['group__race_class__name'],
            'starts': stat['starts'],
            'wins': stat['wins'],
            'podiums': stat['podiums'],
            'win_rate': round(stat['wins'] / stat['starts'] * 100, 1) if stat['starts'] > 0 else 0,
        })

    # Статистика по трассам (только общие)
    track_stats = []
    if other_driver:
        # Находим трассы, где есть результаты обоих пилотов
        common_tracks = RaceResult.objects.filter(
            driver__in=[driver, other_driver]
        ).values('group__page__track_id').annotate(
            driver_count=Count('driver', distinct=True)
        ).filter(driver_count=2).values_list('group__page__track_id', flat=True)

        # Получаем результаты первого пилота на этих трассах
        track_results = results.filter(
            group__page__track_id__in=common_tracks
        ).values(
            'group__page__track__name',
            'group__page__track__slug'
        ).annotate(
            starts=Count('id'),
            wins=Count('id', filter=Q(position=1)),
            best_position=Min('position')
        ).order_by('-starts')[:5]

        for stat in track_results:
            track_stats.append({
                'name': stat['group__page__track__name'],
                'slug': stat['group__page__track__slug'],
                'starts': stat['starts'],
                'wins': stat['wins'],
                'best': stat['best_position'],
            })
    else:
        # Если второго пилота нет - показываем все трассы
        track_results = results.values(
            'group__page__track__name',
            'group__page__track__slug'
        ).annotate(
            starts=Count('id'),
            wins=Count('id', filter=Q(position=1)),
            best_position=Min('position')
        ).filter(group__page__track__isnull=False).order_by('-starts')[:5]

        for stat in track_results:
            track_stats.append({
                'name': stat['group__page__track__name'],
                'slug': stat['group__page__track__slug'],
                'starts': stat['starts'],
                'wins': stat['wins'],
                'best': stat['best_position'],
            })
    # Статистика по погоде
    dry_results = results.filter(group__precipitation__lt=0.1)
    wet_results = results.filter(group__precipitation__gte=0.1)

    # === ДАННЫЕ ДЛЯ ГРАФИКА (только общие гонки, сортировка по ДАТЕ ПРОВЕДЕНИЯ) ===
    chart_data = []

    if other_driver:
        from django.db.models import Count

        # Находим все группы, где есть оба пилота
        common_groups = RaceResult.objects.filter(
            driver__in=[driver, other_driver]
        ).values('group_id').annotate(
            driver_count=Count('driver', distinct=True)
        ).filter(driver_count=2).values_list('group_id', flat=True)

        print(f"🔍 Найдено общих групп: {len(common_groups)}")

        if not common_groups:
            # Если общих гонок нет
            chart_data = []
            print("❌ Общих этапов нет")
        else:
            # Получаем все результаты для этих групп
            all_results = RaceResult.objects.filter(
                group_id__in=common_groups
            ).select_related(
                'group__page'
            )

            # Группируем по group_id
            results_by_group = {}
            for res in all_results:
                group_id = res.group_id
                if group_id not in results_by_group:
                    # Получаем дату окончания гонки
                    page = res.group.page
                    occurrence = EventOccurrence.objects.filter(event=page).first()
                    event_date = occurrence.end if occurrence else page.last_published_at

                    # Формируем уникальное название с датой
                    if event_date:
                        event_name = f"{page.title} ({event_date.strftime('%d.%m.%Y')})"
                    else:
                        event_name = page.title

                    results_by_group[group_id] = {
                        'event': event_name,
                        'date': event_date,
                        driver.id: None,
                        other_driver.id: None
                    }
                results_by_group[group_id][res.driver_id] = res.points

            # Сортируем по дате (от новых к старым)
            sorted_groups = sorted(results_by_group.values(), key=lambda x: x['date'], reverse=True)

            # Берем последние 10 или сколько есть
            max_points = min(10, len(sorted_groups))
            display_groups = sorted_groups[:max_points]

            # Формируем данные (уже с проверкой, что оба результата есть)
            for group in display_groups:
                if group[driver.id] is not None and group[other_driver.id] is not None:
                    chart_data.append({
                        'event': group['event'],
                        'points': group[driver.id],
                        'other_points': group[other_driver.id],
                        #'date': group['date'],
                    })
                    print(f"✅ Добавлено: {group['event']}, {driver.full_name}: {group[driver.id]}, {other_driver.full_name}: {group[other_driver.id]}")

            print(f"📊 Всего точек на графике: {len(chart_data)}")
    else:
        # Если второго пилота нет - показываем последние 10 гонок пилота
        recent_results = results.order_by('-group__page__last_published_at')[:10]
        for res in recent_results:
            occurrence = EventOccurrence.objects.filter(event=res.group.page).first()
            event_date = occurrence.end if occurrence else res.group.page.last_published_at
            chart_data.append({
                'event': res.group.page.title[:20] + '...' if len(res.group.page.title) > 20 else res.group.page.title,
                'points': res.points,
                'position': res.position,
                'date': event_date,
            })
        chart_data.sort(key=lambda x: x['date'], reverse=True)
    # ====================================================


    # === НОРМИРОВАННЫЙ РЕЙТИНГ ===
    normalized_rating = 0
    if all_drivers and len(all_drivers) > 0 and driver.rating_score:
        # Собираем все рейтинги для нормировки
        ratings = []
        for d in all_drivers:
            if d.rating_score:
                ratings.append(d.rating_score)

        if ratings:
            min_rating = min(ratings)
            max_rating = max(ratings)
            rating_range = max_rating - min_rating if max_rating > min_rating else 1

            # Нормируем текущего пилота
            normalized_rating = round(
                (driver.rating_score - min_rating) / rating_range * 100, 1
            )

    print(f"=== ОТЛАДКА === for driver {driver.id}")
    print(f"other_driver: {other_driver}")
    print(f"chart_data length: {len(chart_data)}")
    if chart_data:
        print(f"First item keys: {chart_data[0].keys()}")
    print(f"📅 Порядок этапов для {driver.full_name}:")
    for i, d in enumerate(chart_data):
        # print(f"   {i}: {d['event']} - {d['date']}")
        print(f"   {i}: {d['event']}")

    print(f"⚠️ ИТОГО chart_data для {driver.full_name}: {len(chart_data)} элементов")
    for i, d in enumerate(chart_data):
        print(f"   {i}: {d['event']} = {d['points']} vs {d['other_points']}")
    print(f"⚠️ ТИП chart_data: {type(chart_data)}")
    print(f"⚠️ ID chart_data: {id(chart_data)}")

    return {
        'total_starts': total_starts,
        'wins': wins,
        'podiums': podiums,
        'win_rate': round(wins / total_starts * 100, 1) if total_starts > 0 else 0,
        'podium_rate': round(podiums / total_starts * 100, 1) if total_starts > 0 else 0,
        'avg_position': round(results.aggregate(avg=Avg('position'))['avg'] or 0, 2),
        'dry_wins': dry_results.filter(position=1).count(),
        'dry_total': dry_results.count(),
        'wet_wins': wet_results.filter(position=1).count(),
        'wet_total': wet_results.count(),
        'class_stats': class_stats,
        'track_stats': track_stats,
        'chart_data': chart_data,
        'rating': {
            'bt': driver.rating_score,
            'pr': getattr(driver, 'pagerank_score', 0),
            'ensemble': driver.ensemble_score,
        },
        'normalized_rating': normalized_rating,
    }



def compare_models_view(request):
    """
    Страница сравнения моделей Брэдли-Терри и PageRank
    """
    current_site = Site.find_for_request(request)

    from .models import Driver, RaceClass
    from django.db.models import Q

    # Получаем класс для фильтрации
    class_id = request.GET.get('class')
    if class_id and class_id.isdigit():
        class_id = int(class_id)
    else:
        # По умолчанию первый класс
        first_class = RaceClass.objects.first()
        class_id = first_class.id if first_class else None

    # Получаем всех пилотов с рейтингами
    drivers = Driver.objects.exclude(rating_by_class={}).exclude(pagerank_by_class={})

    result_drivers = []

    for driver in drivers:
        bt_data = driver.rating_by_class.get(str(class_id), {})
        pr_data = driver.pagerank_by_class.get(str(class_id), {})

        if bt_data and pr_data:
            bt_score = bt_data.get('score', 0)
            pr_score = pr_data.get('score', 0)
            starts = bt_data.get('starts', 0)

            # Получаем статистику для этого класса
            from .models import RaceResult
            results = RaceResult.objects.filter(
                driver=driver,
                group__race_class_id=class_id
            )
            race_count = results.count()
            win_count = results.filter(position=1).count()
            podium_count = results.filter(position__in=[1,2,3]).count()
            win_percentage = round(win_count / race_count * 100, 1) if race_count > 0 else 0

            driver.race_count = race_count
            driver.win_count = win_count
            driver.podium_count = podium_count
            driver.win_percentage = win_percentage
            driver.bt_score = bt_score
            driver.pr_score = pr_score
            driver.starts = starts

            result_drivers.append(driver)

    # Нормируем обе модели для сравнения (0-100)
    if result_drivers:
        bt_scores = [d.bt_score for d in result_drivers]
        pr_scores = [d.pr_score for d in result_drivers]

        bt_min, bt_max = min(bt_scores), max(bt_scores)
        pr_min, pr_max = min(pr_scores), max(pr_scores)

        bt_range = bt_max - bt_min if bt_max > bt_min else 1
        pr_range = pr_max - pr_min if pr_max > pr_min else 1

        for driver in result_drivers:
            driver.bt_normalized = round(
                (driver.bt_score - bt_min) / bt_range * 100, 1
            )
            driver.pr_normalized = round(
                (driver.pr_score - pr_min) / pr_range * 100, 1
            )
            driver.diff = round(driver.bt_normalized - driver.pr_normalized, 1)

    # Сортируем по разнице (самые большие расхождения)
    result_drivers.sort(key=lambda x: abs(x.diff), reverse=True)

    # Получаем все классы для выпадающего списка
    classes = RaceClass.objects.all().order_by('name')

    return render(request, "coderedcms/snippets/compare_models_page.html", {
        "drivers": result_drivers,
        "classes": classes,
        "selected_class_id": class_id,
        "site": current_site,
        "page": None,
    })
def weights_table_view(request):
    """
    Возвращает актуальные веса контекстной модели для отображения в таблице
    """
    from .models import Driver, RaceClass

    # Берём первый класс (например, Mini) для демонстрации
    # Можно сделать выбор класса через GET-параметр, но пока упростим
    first_class = RaceClass.objects.first()
    if not first_class:
        return render(request, "coderedcms/snippets/weights_table.html", {
            "weights": None
        })

    # Ищем пилота с заполненными весами
    driver_with_weights = Driver.objects.exclude(context_weights={}).first()

    if driver_with_weights and driver_with_weights.context_weights:
        weights = driver_with_weights.context_weights
        last_updated = driver_with_weights.context_updated_at
    else:
        weights = None
        last_updated = None

    return render(request, "coderedcms/snippets/weights_table.html", {
        "weights": weights,
        "last_updated": last_updated,
    })
def chassis_track_matrix_view(request):
    """
    Тепловая карта эффективности шасси на разных трассах
    """
    current_site = Site.find_for_request(request)

    from .models import Chassis, Track, RaceResult, RaceClass
    from django.db.models import Avg, Count, Q

    # Получаем все классы для вкладок
    all_classes = RaceClass.objects.all()
    class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                   'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 Masters']
    classes = sorted(all_classes,
                     key=lambda x: class_order.index(x.name) if x.name in class_order else 999)

    # Получаем выбранный класс
    class_id = request.GET.get('class')
    if class_id and class_id.isdigit():
        class_id = int(class_id)
    else:
        class_id = None

    # Получаем все шасси и трассы
    chassis_list = Chassis.objects.all().order_by('name')
    tracks_list = Track.objects.all().order_by('name')

    # Базовый queryset
    base_qs = RaceResult.objects.all()
    if class_id:
        base_qs = base_qs.filter(group__race_class_id=class_id)

    # Создаём матрицу данных
    matrix_data = {}
    max_win_rate = 0

    for chassis in chassis_list:
        matrix_data[chassis.id] = {}

        for track in tracks_list:
            # Результаты этого шасси на этой трассе в выбранном классе
            results = base_qs.filter(
                chassis_new=chassis,
                group__page__track=track
            )

            total = results.count()
            wins = results.filter(position=1).count()
            podiums = results.filter(position__in=[1,2,3]).count()

            win_rate = round(wins / total * 100, 1) if total > 0 else 0
            podium_rate = round(podiums / total * 100, 1) if total > 0 else 0

            if win_rate > max_win_rate:
                max_win_rate = win_rate

            matrix_data[chassis.id][track.id] = {
                'total': total,
                'wins': wins,
                'podiums': podiums,
                'win_rate': win_rate,
                'podium_rate': podium_rate
            }

    context = {
        'chassis_list': chassis_list,
        'tracks_list': tracks_list,
        'matrix_data': matrix_data,
        'max_win_rate': max_win_rate,
        'classes': classes,
        'selected_class': class_id,
        'site': current_site,
        'page': None,
    }

    return render(request, "coderedcms/snippets/chassis_track_matrix.html", context)

def weather_impact_view(request):
    """
    Расширенная страница анализа влияния погоды на результаты
    """
    current_site = Site.find_for_request(request)

    from .models import RaceResult, Chassis, RaceClass, Driver, Track
    from django.db.models import Avg, Count, Q, Sum
    import json
    from django.utils import timezone

    # Получаем все классы для фильтра
    class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                   'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 32+']
    all_classes = list(RaceClass.objects.all())
    classes = sorted(all_classes, key=lambda x: class_order.index(x.name) if x.name in class_order else 999)

    selected_class_id = request.GET.get('class')
    if selected_class_id and selected_class_id.isdigit():
        selected_class_id = int(selected_class_id)
    else:
        selected_class_id = classes[0].id if classes else None

    # Базовый queryset
    base_qs = RaceResult.objects.all()
    if selected_class_id:
        base_qs = base_qs.filter(group__race_class_id=selected_class_id)

    # Получаем выбранное шасси для температурного графика
    selected_chassis_id = request.GET.get('chassis')
    if selected_chassis_id and selected_chassis_id.isdigit():
        selected_chassis_id = int(selected_chassis_id)
    else:
        selected_chassis_id = None

    # 1. Данные для графика зависимости от температуры (с фильтром по шасси)
    temp_data = []
    if selected_chassis_id:
        temp_qs = base_qs.filter(chassis_new_id=selected_chassis_id)
        chassis_name = Chassis.objects.get(id=selected_chassis_id).name
    else:
        temp_qs = base_qs
        chassis_name = "Все шасси"

    for temp in range(-10, 41, 5):
        results = temp_qs.filter(
            group__air_temperature__gte=temp,
            group__air_temperature__lt=temp+5
        )
        total = results.count()
        wins = results.filter(position=1).count()
        win_rate = round(wins / total * 100, 1) if total > 0 else 0

        if total >= 3:
            temp_data.append({
                'range': f"{temp}..{temp+5}°C",
                'win_rate': win_rate,
                'total': total
            })

    # 2. Сравнение сухо/дождь (глобальное)
    dry_results = base_qs.filter(group__precipitation__lt=0.1)
    wet_results = base_qs.filter(group__precipitation__gte=0.1)

    dry_stats = {
        'total': dry_results.count(),
        'wins': dry_results.filter(position=1).count(),
        'podiums': dry_results.filter(position__in=[1,2,3]).count(),
    }
    wet_stats = {
        'total': wet_results.count(),
        'wins': wet_results.filter(position=1).count(),
        'podiums': wet_results.filter(position__in=[1,2,3]).count(),
    }

    dry_stats['win_rate'] = round(dry_stats['wins'] / dry_stats['total'] * 100, 1) if dry_stats['total'] > 0 else 0
    wet_stats['win_rate'] = round(wet_stats['wins'] / wet_stats['total'] * 100, 1) if wet_stats['total'] > 0 else 0

    # 3. Анализ по пилотам (кто лучше в дождь)
    driver_weather_stats = []

    # Берем пилотов с минимум 5 стартами в сухо и 3 в дождь
    for driver in Driver.objects.filter(raceresult__isnull=False).distinct():
        driver_results = base_qs.filter(driver=driver)

        dry_driver = driver_results.filter(group__precipitation__lt=0.1)
        wet_driver = driver_results.filter(group__precipitation__gte=0.1)

        dry_total = dry_driver.count()
        wet_total = wet_driver.count()

        if dry_total >= 5 and wet_total >= 3:
            dry_wins = dry_driver.filter(position=1).count()
            wet_wins = wet_driver.filter(position=1).count()

            driver_weather_stats.append({
                'driver': driver,
                'dry_total': dry_total,
                'dry_wins': dry_wins,
                'dry_win_rate': round(dry_wins / dry_total * 100, 1),
                'wet_total': wet_total,
                'wet_wins': wet_wins,
                'wet_win_rate': round(wet_wins / wet_total * 100, 1),
                'diff': round((dry_wins / dry_total * 100) - (wet_wins / wet_total * 100), 1)
            })

    # Сортируем по убыванию эффективности в дождь (чем меньше diff, тем лучше в дождь)
    driver_weather_stats.sort(key=lambda x: x['diff'])
    driver_weather_stats = driver_weather_stats[:20]  # Топ-20

    # 4. Анализ по трассам
    track_weather_stats = []

    for track in Track.objects.all():
        track_results = base_qs.filter(group__page__track=track)

        if track_results.exists():
            total_races = track_results.count()
            wet_races = track_results.filter(group__precipitation__gte=0.1).count()
            wet_percentage = round(wet_races / total_races * 100, 1) if total_races > 0 else 0

            # Анализ влияния дождя на результаты
            dry_on_track = track_results.filter(group__precipitation__lt=0.1)
            wet_on_track = track_results.filter(group__precipitation__gte=0.1)

            dry_win_rate = round(dry_on_track.filter(position=1).count() / dry_on_track.count() * 100, 1) if dry_on_track.count() > 0 else 0
            wet_win_rate = round(wet_on_track.filter(position=1).count() / wet_on_track.count() * 100, 1) if wet_on_track.count() > 0 else 0

            impact = round(wet_win_rate - dry_win_rate, 1)

            track_weather_stats.append({
                'track': track,
                'total_races': total_races,
                'wet_races': wet_races,
                'wet_percentage': wet_percentage,
                'dry_win_rate': dry_win_rate,
                'wet_win_rate': wet_win_rate,
                'impact': impact  # положительный - дождь помогает, отрицательный - мешает
            })

    # Сортируем по проценту дождевых гонок
    track_weather_stats.sort(key=lambda x: x['wet_percentage'], reverse=True)
    track_weather_stats = track_weather_stats[:15]  # Топ-15

    # 5. Сезонный анализ (распределение по месяцам)
    monthly_stats = []
    current_year = timezone.now().year

    for month in range(1, 13):
        month_results = base_qs.filter(
            group__page__occurrences__start__year__gte=current_year-2,
            group__page__occurrences__start__month=month
        )

        total = month_results.count()
        wet = month_results.filter(group__precipitation__gte=0.1).count()
        wet_percentage = round(wet / total * 100, 1) if total > 0 else 0

        monthly_stats.append({
            'month': month,
            'month_name': ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
                          'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'][month-1],
            'total': total,
            'wet': wet,
            'wet_percentage': wet_percentage
        })

    # 6. Шасси в дождь vs сухо (улучшенная версия)
    chassis_dry_wet = []
    for chassis in Chassis.objects.all():
        chassis_results = base_qs.filter(chassis_new=chassis)

        dry_chassis = chassis_results.filter(group__precipitation__lt=0.1)
        wet_chassis = chassis_results.filter(group__precipitation__gte=0.1)

        dry_total = dry_chassis.count()
        wet_total = wet_chassis.count()

        if dry_total >= 3 or wet_total >= 3:
            dry_win = dry_chassis.filter(position=1).count()
            wet_win = wet_chassis.filter(position=1).count()

            chassis_dry_wet.append({
                'chassis': chassis,
                'dry_total': dry_total,
                'dry_wins': dry_win,
                'dry_win_rate': round(dry_win / dry_total * 100, 1) if dry_total > 0 else 0,
                'wet_total': wet_total,
                'wet_wins': wet_win,
                'wet_win_rate': round(wet_win / wet_total * 100, 1) if wet_total > 0 else 0,
                'diff': round((dry_win / dry_total * 100 if dry_total > 0 else 0) -
                              (wet_win / wet_total * 100 if wet_total > 0 else 0), 1)
            })

    chassis_dry_wet.sort(key=lambda x: x['diff'])

    # 7. Все шасси для выпадающего списка
    all_chassis = Chassis.objects.all().order_by('name')

    # 8. Веса контекстной модели
    weights_driver = Driver.objects.exclude(context_weights={}).first()
    context_weights = weights_driver.context_weights if weights_driver else None

    return render(request, "coderedcms/snippets/weather_impact.html", {
        "classes": classes,
        "selected_class_id": selected_class_id,
        "selected_chassis_id": selected_chassis_id,
        "all_chassis": all_chassis,
        "chassis_name": chassis_name,
        "temp_data": json.dumps(temp_data),
        "dry_stats": dry_stats,
        "wet_stats": wet_stats,
        "driver_weather_stats": driver_weather_stats,
        "track_weather_stats": track_weather_stats,
        "monthly_stats": monthly_stats,
        "chassis_dry_wet": chassis_dry_wet,
        "context_weights": context_weights,
        "site": current_site,
        "page": None,
    })
from django.http import JsonResponse

def drivers_api(request):
    """
    Возвращает список всех пилотов в формате JSON для поиска
    """
    from .models import Driver

    drivers = Driver.objects.all().order_by('last_name', 'first_name')

    data = {
        'items': [
            {
                'id': d.id,
                'full_name': d.full_name,
                'first_name': d.first_name,
                'last_name': d.last_name,
                'city': d.city or '',
            }
            for d in drivers
        ]
    }
    return JsonResponse(data)

def teams_api(request):
    """Возвращает список всех команд в формате JSON для поиска"""
    from .models import Team
    teams = Team.objects.all().order_by('name')
    data = {
        'items': [
            {
                'id': t.id,
                'name': t.name,
            }
            for t in teams
        ]
    }
    return JsonResponse(data)

def chassis_api(request):
    """Возвращает список всех шасси в формате JSON для поиска"""
    from .models import Chassis
    chassis = Chassis.objects.all().order_by('name')
    data = {
        'items': [
            {
                'id': c.id,
                'name': c.name,
            }
            for c in chassis
        ]
    }
    return JsonResponse(data)

def staff_detail_view(request, slug):
    staff = get_object_or_404(TeamStaff, slug=slug)
    current_site = Site.find_for_request(request)

    # Получаем все команды сотрудника (активные и прошлые)
    memberships = TeamStaffMembership.objects.filter(
        staff=staff
    ).select_related('team').order_by('-joined_at')

    current_team = memberships.filter(is_active=True).first()
    previous_teams = memberships.filter(is_active=False)

    return render(request, "coderedcms/snippets/staff_page.html", {
        "staff": staff,
        "object": staff,
        "page": staff,
        "current_team": current_team.team if current_team else None,
        "previous_teams": previous_teams,
        "site": current_site,
    })

def matrix_cell_detail_api(request):
    from .models import RaceClass
    """
    API для получения детальной информации по ячейке матрицы
    """
    chassis_slug = request.GET.get('chassis')
    track_id = request.GET.get('track')
    class_id = request.GET.get('class')

    if not chassis_slug or not track_id:
        return JsonResponse({'error': 'Не указаны параметры chassis или track'}, status=400)

    try:
        # Получаем шасси по slug
        chassis = Chassis.objects.get(slug=chassis_slug)
        track = Track.objects.get(id=track_id)
    except Chassis.DoesNotExist:
        return JsonResponse({'error': f'Шасси с slug {chassis_slug} не найдено'}, status=404)
    except Track.DoesNotExist:
        return JsonResponse({'error': f'Трасса с id {track_id} не найдена'}, status=404)
    except ValueError:
        return JsonResponse({'error': 'Некорректный ID трассы'}, status=400)

    # Базовый queryset
    results = RaceResult.objects.filter(
        chassis_new=chassis,
        group__page__track=track
    ).select_related(
        'driver', 'team', 'group__page', 'group__race_class'
    )

    class_name = "Все классы"
    if class_id and class_id.isdigit() and int(class_id) > 0:
        results = results.filter(group__race_class_id=class_id)
        try:
            class_name = RaceClass.objects.get(id=class_id).name
        except RaceClass.DoesNotExist:
            class_name = "Класс не найден"

    total = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1,2,3]).count()
    win_rate = round(wins / total * 100, 1) if total > 0 else 0

    # Топ-5 пилотов на этом шасси/трассе
    from django.db.models import Count, Q
    top_drivers = results.values(
        'driver__id',
        'driver__first_name',
        'driver__last_name'
    ).annotate(
        starts=Count('id'),
        wins=Count('id', filter=Q(position=1))
    ).order_by('-wins', '-starts')[:5]

    # Последние 10 гонок
    recent_races = results.order_by('-group__page__last_published_at')[:10]
    races_list = []
    for race in recent_races:
        occurrence = EventOccurrence.objects.filter(event=race.group.page).first()
        event_date = occurrence.end if occurrence else race.group.page.last_published_at
        races_list.append({
            'date': event_date.strftime('%d.%m.%Y') if event_date else '—',
            'event': race.group.page.title,
            'driver': race.driver.full_name,
            'position': race.position,
            'points': race.points,
            'class': race.group.race_class.name,
        })

    data = {
        'chassis': chassis.name,
        'track': track.name,
        'class': class_name,
        'total': total,
        'wins': wins,
        'podiums': podiums,
        'win_rate': win_rate,
        'top_drivers': [
            {
                'name': f"{d['driver__first_name']} {d['driver__last_name']}",
                'starts': d['starts'],
                'wins': d['wins'],
            } for d in top_drivers
        ],
        'recent_races': races_list,
    }

    return JsonResponse(data)

def staff_api(request, staff_id):
    """API для получения данных сотрудника"""
    try:
        staff = TeamStaff.objects.get(id=staff_id)
        data = {
            'id': staff.id,
            'last_name': staff.last_name,
            'first_name': staff.first_name,
            'middle_name': staff.middle_name or '',
            'position': staff.position or '',
            'biography': staff.biography or '',
            'phone': staff.phone or '',
            'email': staff.email or '',
        }
        return JsonResponse(data)
    except TeamStaff.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

def tyre_analysis_view(request):
    """
    Страница шинного анализа: матрица "Шасси × Шины" и анализ совместимости
    """
    current_site = Site.find_for_request(request)

    from .models import Chassis, Tyre, RaceResult, RaceClass, TyreBrand, TyreType
    from django.db.models import Count, Q, Avg
    import json

    # Получаем все классы для фильтра
    class_order = ['Rotax Max Micro', 'Rotax Max Mini', 'Rotax Max Junior',
                   'Rotax Max Senior', 'Rotax Max DD2', 'Rotax Max DD2 32+']
    all_classes = list(RaceClass.objects.all())
    classes = sorted(all_classes, key=lambda x: class_order.index(x.name) if x.name in class_order else 999)

    selected_class_id = request.GET.get('class')
    if selected_class_id and selected_class_id.isdigit():
        selected_class_id = int(selected_class_id)
    else:
        selected_class_id = classes[0].id if classes else None

    # Получаем все шасси и шины
    chassis_list = Chassis.objects.filter(race_results__isnull=False).distinct().order_by('name')
    tyres_list = Tyre.objects.filter(race_groups__isnull=False).distinct().order_by('brand__name', 'type__name')

    # Базовый queryset
    base_qs = RaceResult.objects.all()
    if selected_class_id:
        base_qs = base_qs.filter(group__race_class_id=selected_class_id)

    # 1. Матрица "Шасси × Шины"
    matrix_data = {}
    max_win_rate = 0

    for chassis in chassis_list:
        matrix_data[chassis.id] = {}

        for tyre in tyres_list:
            results = base_qs.filter(
                chassis_new=chassis,
                group__tyre=tyre
            )

            total = results.count()
            wins = results.filter(position=1).count()
            win_rate = round(wins / total * 100, 1) if total > 0 else 0

            if win_rate > max_win_rate:
                max_win_rate = win_rate

            matrix_data[chassis.id][tyre.id] = {
                'total': total,
                'wins': wins,
                'win_rate': win_rate
            }

    # 2. Лучшие сочетания "Шасси + Шины" (топ-20 по Win Rate)
    best_combinations = []

    for chassis in chassis_list:
        for tyre in tyres_list:
            results = base_qs.filter(
                chassis_new=chassis,
                group__tyre=tyre
            )
            total = results.count()
            if total >= 5:  # Минимум 5 стартов для статистики
                wins = results.filter(position=1).count()
                win_rate = round(wins / total * 100, 1)

                best_combinations.append({
                    'chassis': chassis,
                    'tyre': tyre,
                    'total': total,
                    'wins': wins,
                    'win_rate': win_rate
                })

    best_combinations.sort(key=lambda x: x['win_rate'], reverse=True)
    best_combinations = best_combinations[:20]

    # 3. Статистика по производителям шин
    brand_stats = []

    for brand in TyreBrand.objects.all():
        brand_results = base_qs.filter(group__tyre__brand=brand)
        total = brand_results.count()

        if total > 0:
            wins = brand_results.filter(position=1).count()
            podiums = brand_results.filter(position__in=[1,2,3]).count()

            # По типам шин внутри бренда
            type_stats = []
            for tyre_type in TyreType.objects.all():
                type_results = brand_results.filter(group__tyre__type=tyre_type)
                type_total = type_results.count()
                if type_total > 0:
                    type_wins = type_results.filter(position=1).count()
                    type_stats.append({
                        'type': tyre_type,
                        'total': type_total,
                        'wins': type_wins,
                        'win_rate': round(type_wins / type_total * 100, 1)
                    })

            brand_stats.append({
                'brand': brand,
                'total': total,
                'wins': wins,
                'podiums': podiums,
                'win_rate': round(wins / total * 100, 1),
                'podium_rate': round(podiums / total * 100, 1),
                'type_stats': type_stats
            })

    brand_stats.sort(key=lambda x: x['win_rate'], reverse=True)

    # 4. Анализ "Какое шасси лучше с какими шинами"
    chassis_tyre_preference = []

    for chassis in chassis_list[:10]:  # Топ-10 шасси
        chassis_results = base_qs.filter(chassis_new=chassis)

        preference = []
        for tyre in tyres_list:
            results = chassis_results.filter(group__tyre=tyre)
            total = results.count()
            if total >= 3:
                wins = results.filter(position=1).count()
                win_rate = round(wins / total * 100, 1)
                preference.append({
                    'tyre': tyre,
                    'win_rate': win_rate,
                    'total': total
                })

        if preference:
            preference.sort(key=lambda x: x['win_rate'], reverse=True)
            chassis_tyre_preference.append({
                'chassis': chassis,
                'best_tyre': preference[0],
                'all_preferences': preference[:5]  # Топ-5 шин для этого шасси
            })

    context = {
        'classes': classes,
        'selected_class_id': selected_class_id,
        'chassis_list': chassis_list,
        'tyres_list': tyres_list,
        'matrix_data': matrix_data,
        'max_win_rate': max_win_rate,
        'best_combinations': best_combinations,
        'brand_stats': brand_stats,
        'chassis_tyre_preference': chassis_tyre_preference,
        'site': current_site,
        'page': None,
    }

    return render(request, "coderedcms/snippets/tyre_analysis.html", context)
