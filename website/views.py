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

    # Пытаемся найти текущий сайт
    current_site = Site.find_for_request(request)

    # Получаем уникальных пилотов, которые выступали за эту команду
    team_drivers = Driver.objects.filter(
        raceresult__team=team
    ).distinct().order_by('last_name', 'first_name')

    # Для каждого пилота получаем последний класс, в котором он выступал за эту команду
    for driver in team_drivers:
        last_result = RaceResult.objects.filter(
            team=team,
            driver=driver
        ).select_related('group__race_class').order_by('-group__page__last_published_at').first()

        if last_result:
            driver.last_class = last_result.group.race_class.name
        else:
            driver.last_class = None

    return render(request, "coderedcms/snippets/team_page.html", {
        "team": team,
        "object": team,
        "page": team,
        "team_drivers": team_drivers,  # Передаем список уникальных пилотов
        "site": current_site,
    })

def track_detail_view(request, slug):
    track = get_object_or_404(Track, slug=slug)

    # Пытаемся найти текущий сайт
    current_site = Site.find_for_request(request)

    # Получаем все события (этапы), которые проходили на этой трассе
    from .models import EventPage
    events = EventPage.objects.live().filter(track=track).order_by('-first_published_at')

    return render(request, "coderedcms/snippets/track_page.html", {
        "track": track,
        "object": track,
        "page": track,
        "events": events,
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

    # Получаем все результаты с этим двигателем
    results = RaceResult.objects.filter(
        group__engine=engine
    ).select_related(
        'driver', 'team', 'group__page', 'group__race_class', 'group__tyre', 'chassis_new'
    ).order_by('-group__page__last_published_at')

    # Статистика
    total_starts = results.count()
    wins = results.filter(position=1).count()
    podiums = results.filter(position__in=[1,2,3]).count()

    return render(request, "coderedcms/snippets/engine_page.html", {
        "engine": engine,
        "object": engine,
        "page": engine,
        "results": results,
        "total_starts": total_starts,
        "wins": wins,
        "podiums": podiums,
        "win_percentage": round((wins/total_starts*100),1) if total_starts else 0,
        "podium_percentage": round((podiums/total_starts*100),1) if total_starts else 0,
        "site": current_site,
    })
def compare_view(request):
    current_site = Site.find_for_request(request)

    # Получаем все шасси для выпадающих списков
    all_chassis = Chassis.objects.all().order_by('name')

    # Получаем выбранные шасси из GET-параметров
    chassis1_slug = request.GET.get('chassis1')
    chassis2_slug = request.GET.get('chassis2')

    # Если передан параметр 'chassis' (с одной страницы), подставляем его как первое
    if not chassis1_slug and request.GET.get('chassis'):
        chassis1_slug = request.GET.get('chassis')

    chassis1 = None
    chassis2 = None
    stats1 = None
    stats2 = None

    if chassis1_slug:
        chassis1 = get_object_or_404(Chassis, slug=chassis1_slug)
        stats1 = get_chassis_stats(chassis1)

    if chassis2_slug:
        chassis2 = get_object_or_404(Chassis, slug=chassis2_slug)
        stats2 = get_chassis_stats(chassis2)

    return render(request, "coderedcms/snippets/compare_page.html", {
        "all_chassis": all_chassis,
        "chassis1": chassis1,
        "chassis2": chassis2,
        "stats1": stats1,
        "stats2": stats2,
        "site": current_site,
        "page": None,  # Для совместимости с шаблоном
    })

def get_chassis_stats(chassis):
    """Вспомогательная функция для получения статистики шасси"""
    results = RaceResult.objects.filter(chassis_new=chassis)

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

    from .models import Chassis, Track, RaceResult
    from django.db.models import Avg, Count, Q

    # Получаем все шасси и трассы
    chassis_list = Chassis.objects.all().order_by('name')
    tracks_list = Track.objects.all().order_by('name')

    # Создаём матрицу данных в виде словаря
    matrix_data = {}
    max_win_rate = 0

    for chassis in chassis_list:
        matrix_data[chassis.id] = {}

        for track in tracks_list:
            # Результаты этого шасси на этой трассе
            results = RaceResult.objects.filter(
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
        'matrix_data': matrix_data,  # теперь это словарь, а не JSON
        'max_win_rate': max_win_rate,
        'site': current_site,
        'page': None,
    }

    return render(request, "coderedcms/snippets/chassis_track_matrix.html", context)

def weather_impact_view(request):
    """
    Страница анализа влияния погоды на результаты
    """
    current_site = Site.find_for_request(request)

    from .models import RaceResult, Chassis, RaceClass
    from django.db.models import Avg, Count, Q
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

    # Базовый queryset
    base_qs = RaceResult.objects.all()
    if selected_class_id:
        base_qs = base_qs.filter(group__race_class_id=selected_class_id)

    # 1. Данные для графика зависимости от температуры
    temp_data = []
    for temp in range(0, 41, 5):  # от 0 до 40 с шагом 5
        results = base_qs.filter(
            group__air_temperature__gte=temp,
            group__air_temperature__lt=temp+5
        )
        total = results.count()
        wins = results.filter(position=1).count()
        win_rate = round(wins / total * 100, 1) if total > 0 else 0

        if total >= 5:  # минимум 5 заездов для статистики
            temp_data.append({
                'range': f"{temp}-{temp+5}°C",
                'win_rate': win_rate,
                'total': total
            })

    # 2. Сравнение сухо/дождь
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

    # 3. Какое шасси лучше в дождь
    chassis_dry_wet = []
    for chassis in Chassis.objects.all():
        chassis_results = base_qs.filter(chassis_new=chassis)

        dry_chassis = chassis_results.filter(group__precipitation__lt=0.1)
        wet_chassis = chassis_results.filter(group__precipitation__gte=0.1)

        dry_total = dry_chassis.count()
        wet_total = wet_chassis.count()

        if dry_total >= 3 or wet_total >= 3:  # минимум 3 заезда
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

    # Сортируем по разнице (кто лучше в дождь)
    chassis_dry_wet.sort(key=lambda x: x['diff'])

    # 4. Веса контекстной модели
    from .models import Driver
    weights_driver = Driver.objects.exclude(context_weights={}).first()
    context_weights = weights_driver.context_weights if weights_driver else None

    return render(request, "coderedcms/snippets/weather_impact.html", {
        "classes": classes,
        "selected_class_id": selected_class_id,
        "temp_data": json.dumps(temp_data),
        "dry_stats": dry_stats,
        "wet_stats": wet_stats,
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
