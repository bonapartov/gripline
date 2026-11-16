"""Таблицы рейтинга, сравнение пилотов, статистика и публичные API."""

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
    ClassSmoother, _class_ranking_entries, class_min_starts,
    rating_out_reason,
)



def compare_drivers_view(request):
    """
    Страница сравнения двух пилотов
    """
    from django.db.models import Count
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
    from website.models import RaceClass
    classes = RaceClass.objects.for_site()

    # Получаем всех пилотов
    from website.services.demo import without_demo
    all_drivers = without_demo(Driver.objects.all()).order_by('last_name', 'first_name')

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
        print(f"[INFO] Выбран класс {class_id}, найдено пилотов: {filtered_drivers.count()}")

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

    # --- BT вероятность победы ---
    bt_prob = None
    if driver1 and driver2:
        import json, math
        rbc1 = driver1.rating_by_class or {}
        rbc2 = driver2.rating_by_class or {}
        if isinstance(rbc1, str):
            try: rbc1 = json.loads(rbc1)
            except: rbc1 = {}
        if isinstance(rbc2, str):
            try: rbc2 = json.loads(rbc2)
            except: rbc2 = {}
        common_class_ids = set(rbc1.keys()) & set(rbc2.keys())
        if common_class_ids:
            use_class_str = (
                str(class_id) if class_id and str(class_id) in common_class_ids
                else max(common_class_ids, key=lambda k: rbc1.get(k, {}).get('starts', 0))
            )
            bt1 = float(rbc1[use_class_str].get('score', 0))
            bt2 = float(rbc2[use_class_str].get('score', 0))
            s1, s2 = math.exp(bt1), math.exp(bt2)
            prob1 = round(s1 / (s1 + s2) * 100, 1)
            try:
                prob_class_name = RaceClass.objects.get(id=int(use_class_str)).name
            except RaceClass.DoesNotExist:
                prob_class_name = ''
            bt_prob = {
                'prob1': prob1,
                'prob2': round(100 - prob1, 1),
                'class_name': prob_class_name,
            }

    # --- H2H встречи ---
    h2h = None
    if driver1 and driver2:
        common_group_ids = list(
            RaceResult.objects.filter(driver__in=[driver1, driver2])
            .values('group_id')
            .annotate(cnt=Count('driver', distinct=True))
            .filter(cnt=2)
            .values_list('group_id', flat=True)
        )
        if common_group_ids:
            all_h2h_results = RaceResult.objects.filter(
                group_id__in=common_group_ids,
                driver__in=[driver1, driver2],
            ).select_related('group__page', 'group__race_class').annotate(
                group_size=Count('group__class_results'),
                event_end=Subquery(
                    EventOccurrence.objects.filter(
                        event_id=OuterRef('group__page_id')
                    ).order_by('-end').values('end')[:1]
                )
            )
            by_group = {}
            for r in all_h2h_results:
                gid = r.group_id
                if gid not in by_group:
                    by_group[gid] = {
                        'event': r.group.page.title,
                        'class_name': r.group.race_class.name,
                        'date': r.event_end or r.group.page.first_published_at,
                        'group_size': r.group_size,
                        'd1': None, 'd2': None,
                    }
                if r.driver_id == driver1.id:
                    by_group[gid]['d1'] = r.position
                else:
                    by_group[gid]['d2'] = r.position

            meetings = sorted(
                [v for v in by_group.values() if v['d1'] and v['d2']],
                key=lambda x: x['date'], reverse=True
            )
            d1_wins = sum(1 for m in meetings if m['d1'] < m['d2'])
            d2_wins = sum(1 for m in meetings if m['d2'] < m['d1'])
            h2h = {
                'meetings': len(meetings),
                'd1_wins': d1_wins,
                'd2_wins': d2_wins,
                'list': meetings,
            }

    context = {
        'driver1': driver1,
        'driver2': driver2,
        'stats1': stats1,
        'stats2': stats2,
        'classes': classes,
        'selected_class': class_id,
        'all_drivers': filtered_drivers,
        'bt_prob': bt_prob,
        'h2h': h2h,
        'site': current_site,
        'page': None,
    }
    return render(request, "coderedcms/snippets/compare_drivers.html", context)

def get_driver_stats(driver, class_id=None, all_drivers=None, other_driver=None):
    """
    Вспомогательная функция для получения статистики пилота
    """
    from django.db.models import Count, Avg, Q, Min
    from website.models import RaceResult, EventOccurrence

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

        if not common_groups:
            chart_data = []
        else:
            all_results = RaceResult.objects.filter(
                group_id__in=common_groups,
                driver__in=[driver, other_driver],
            ).select_related('group__page').annotate(
                group_size=Count('group__class_results')
            )

            results_by_group = {}
            for res in all_results:
                gid = res.group_id
                if gid not in results_by_group:
                    page = res.group.page
                    occurrence = EventOccurrence.objects.filter(event=page).first()
                    event_date = occurrence.end if occurrence else page.last_published_at
                    results_by_group[gid] = {
                        'event': f"{page.title} ({event_date.strftime('%d.%m.%Y')})" if event_date else page.title,
                        'date': event_date,
                        driver.id: None,
                        other_driver.id: None,
                    }
                results_by_group[gid][res.driver_id] = {
                    'position': res.position,
                    'group_size': res.group_size,
                }

            sorted_groups = sorted(results_by_group.values(), key=lambda x: x['date'] or '', reverse=True)
            for group in sorted_groups[:10]:
                r1, r2 = group[driver.id], group[other_driver.id]
                if r1 and r2:
                    chart_data.append({
                        'event': group['event'],
                        'pos1': r1['position'],
                        'size1': r1['group_size'],
                        'pos2': r2['position'],
                        'size2': r2['group_size'],
                    })
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


    # === НОРМИРОВАННЫЙ РЕЙТИНГ (байесовский BT, класс с наибольшим числом стартов) ===
    normalized_rating = 0
    import json as _json
    rbc = driver.rating_by_class or {}
    if isinstance(rbc, str):
        try: rbc = _json.loads(rbc)
        except: rbc = {}
    if rbc:
        # тот же расчёт и та же выборка, что в таблице рейтинга и на странице пилота
        best_class_str = max(rbc.keys(), key=lambda k: rbc[k].get('starts', 0))
        entries = _class_ranking_entries(
            int(best_class_str), Driver.objects.exclude(rating_by_class={}), keep_driver_id=driver.id)
        mine = next((e for e in entries if e['driver_id'] == driver.id), None)
        if mine:
            normalized_rating = mine['normalized']

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

    from website.models import Driver, RaceClass
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
            from website.models import RaceResult
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
    classes = RaceClass.objects.for_site()

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
    from website.models import Driver, RaceClass

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

    from website.models import Chassis, Track, RaceResult, RaceClass
    from django.db.models import Avg, Count, Q

    # Получаем все классы для вкладок
    all_classes = RaceClass.objects.for_site()
    classes = list(all_classes)

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

    from website.models import RaceResult, Chassis, RaceClass, Driver, Track
    from django.db.models import Avg, Count, Q, Sum
    import json
    from django.utils import timezone

    # Получаем все классы для фильтра
    classes = list(RaceClass.objects.for_site())

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
    from website.models import Driver

    from website.services.demo import without_demo
    drivers = without_demo(Driver.objects.all()).order_by('last_name', 'first_name')

    data = {
        'items': [
            {
                'id': d.id,
                'full_name': d.full_name,
                'first_name': d.first_name,
                'last_name': d.last_name,
                'city': d.city or '',
                'absolute_url': d.get_absolute_url(),
            }
            for d in drivers
        ]
    }
    return JsonResponse(data)


def home_top_drivers_api(request):
    """AJAX endpoint: топ пилотов по классу для главной страницы."""
    import json, statistics as _stats
    from datetime import date as _date
    from website.models import Driver, RaceResult, AnalyticsSettings

    class_id = request.GET.get('class')
    if not class_id or not class_id.isdigit():
        return JsonResponse({'drivers': []})
    class_id = int(class_id)
    class_key = str(class_id)

    _as = AnalyticsSettings.get()

    all_drivers = list(Driver.objects.exclude(rating_by_class={}).exclude(rating_by_class__isnull=True))
    min_starts = class_min_starts(class_id, all_drivers, _as)
    candidates = []
    for driver in all_drivers:
        rbc = driver.rating_by_class
        if isinstance(rbc, str):
            try:
                rbc = json.loads(rbc)
            except Exception:
                rbc = {}
        bt_data = rbc.get(class_key, {})
        if not bt_data:
            continue

        # Давно не выступал или мало стартов — не в таблице (rating_out_reason)
        if rating_out_reason(bt_data, _as, min_starts):
            continue

        results = RaceResult.objects.filter(driver=driver, group__race_class_id=class_id)
        driver.race_count = results.count()
        driver.win_count = results.filter(position=1).count()
        driver._bt_score = bt_data.get('score', 0)
        driver._starts = bt_data.get('starts', 0)
        driver._rating_entry = bt_data
        candidates.append(driver)

    if not candidates:
        return JsonResponse({'drivers': []})

    smoother = ClassSmoother([d._bt_score for d in candidates], _as)
    for d in candidates:
        d._smoothed = smoother.smooth(d._bt_score, d._starts, d._rating_entry)
    candidates.sort(key=lambda x: x._smoothed, reverse=True)
    min_s = candidates[-1]._smoothed
    max_s = candidates[0]._smoothed
    rng = max_s - min_s if max_s > min_s else 1
    for i, d in enumerate(candidates, 1):
        d.rank = i
        d.normalized_rating = round((d._smoothed - min_s) / rng * 100, 1)
    top_drivers = candidates[:5]

    result = []
    for d in top_drivers:
        photo_url = None
        if d.photo:
            from wagtail.images.shortcuts import get_rendition_or_not_found
            rendition = get_rendition_or_not_found(d.photo, 'fill-52x52')
            photo_url = rendition.url
        result.append({
            'rank': d.rank,
            'full_name': d.full_name,
            'url': d.get_absolute_url(),
            'photo_url': photo_url,
            'race_count': d.race_count,
            'win_count': d.win_count,
            'normalized_rating': d.normalized_rating,
        })

    return JsonResponse({'drivers': result})


def team_ratings_view(request):
    """Командный рейтинг — агрегация BT-рейтингов пилотов по командам."""
    import json, statistics as _stats

    current_site = Site.find_for_request(request)

    # Балл пилота — тот же, что в таблице его класса (_class_ranking_entries): та же
    # выборка, сглаживание и нормировка 0–100. Пилоты вне таблицы класса (давно не
    # выступал, мало стартов) в командный рейтинг не входят. До 18.10.2026 здесь читалось
    # несуществующее поле 'bt_score' — у всех пилотов выходило 50, команды не различались.
    all_drivers = list(Driver.objects.exclude(rating_by_class__isnull=True).exclude(rating_by_class={}))
    class_scores = {}  # {class_id_str: {driver_id: балл 0–100}}

    def class_table(class_id_str):
        if class_id_str not in class_scores:
            class_scores[class_id_str] = {
                e['driver_id']: e['normalized']
                for e in _class_ranking_entries(class_id_str, all_drivers)
            }
        return class_scores[class_id_str]

    # Получаем класс_id → name
    class_name_map = {str(c.id): c.name for c in RaceClass.objects.for_site()}
    class_sort = RaceClass.sort_key_map()

    teams = Team.objects.all()
    team_rows = []
    current_team_map = _compute_driver_current_teams()

    for team in teams:
        active_drivers = list(Driver.objects.filter(
            id__in=_get_current_team_driver_ids(team, current_team_map)
        ).distinct())

        if not active_drivers:
            continue

        class_data = {}  # {class_name: {'scores': [], 'drivers': []}}

        for driver in active_drivers:
            rbc = driver.rating_by_class or {}
            if isinstance(rbc, str):
                try:
                    rbc = json.loads(rbc)
                except Exception:
                    rbc = {}
            for class_id_str in rbc:
                if class_id_str not in class_name_map:
                    continue  # класс только для приложения или удалён
                norm = class_table(class_id_str).get(driver.id)
                if norm is None:
                    continue
                class_name = class_name_map[class_id_str]
                class_data.setdefault(class_name, {'scores': [], 'drivers': []})
                class_data[class_name]['scores'].append(norm)
                class_data[class_name]['drivers'].append({
                    'driver': driver,
                    'score': norm,
                })

        if not class_data:
            continue

        sorted_classes = sorted(class_data.items(), key=lambda x: class_sort.get(x[0], 9999))

        # Средний балл команды (по всем классам)
        all_scores = [s for _, d in class_data.items() for s in d['scores']]
        avg_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0

        team_rows.append({
            'team': team,
            'driver_count': len(active_drivers),
            'avg_score': avg_score,
            'classes': [
                {
                    'name': name,
                    'avg': round(sum(d['scores']) / len(d['scores']), 1),
                    'drivers': sorted(d['drivers'], key=lambda x: -x['score']),
                }
                for name, d in sorted_classes
            ],
        })

    team_rows.sort(key=lambda x: -x['avg_score'])
    for i, row in enumerate(team_rows):
        row['rank'] = i + 1

    return render(request, 'coderedcms/snippets/team_ratings.html', {
        'team_rows': team_rows,
        'site': current_site,
    })


def teams_api(request):
    """Возвращает список всех команд в формате JSON для поиска"""
    from website.models import Team
    teams = Team.objects.all().order_by('name')
    data = {
        'items': [
            {
                'id': t.id,
                'name': t.name,
                'absolute_url': t.get_absolute_url(),
            }
            for t in teams
        ]
    }
    return JsonResponse(data)

def chassis_api(request):
    """Возвращает список всех шасси в формате JSON для поиска"""
    from website.models import Chassis
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
