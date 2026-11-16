"""Страницы сотрудников, шинный анализ, объявления и API статистики."""

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
    from website.models import RaceClass
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

    from website.models import Chassis, Tyre, RaceResult, RaceClass, TyreBrand, TyreType
    from django.db.models import Count, Q, Avg
    import json

    # Получаем все классы для фильтра
    classes = list(RaceClass.objects.for_site())

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


# ========== ОБЪЯВЛЕНИЯ ==========
def ads_list(request):
    """Список объявлений"""
    ads_list = Ad.objects.filter(is_active=True)

    # Фильтры
    ad_type = request.GET.get('type')
    if ad_type:
        ads_list = ads_list.filter(ad_type=ad_type)

    category_slug = request.GET.get('category')
    if category_slug:
        ads_list = ads_list.filter(category__slug=category_slug)

    categories = AdCategory.objects.all()

    return render(request, 'website/ads_list.html', {
        'ads': ads_list,
        'categories': categories,
        'current_type': ad_type,
        'current_category': category_slug,
    })


def ads_detail(request, ad_id):
    """Детальная страница объявления"""
    ad = get_object_or_404(Ad, id=ad_id, is_active=True)
    ad.views_count += 1
    ad.save()
    return render(request, 'website/ads_detail.html', {'ad': ad})


@login_required
def ads_create(request):
    """Создание объявления"""
    if request.method == 'POST':
        title = request.POST.get('title')
        ad_type = request.POST.get('ad_type')
        category_id = request.POST.get('category')
        description = request.POST.get('description')
        price = request.POST.get('price')
        location = request.POST.get('location')
        contact_phone = request.POST.get('contact_phone')
        contact_email = request.POST.get('contact_email')
        contact_telegram = request.POST.get('contact_telegram')

        ad = Ad.objects.create(
            author=request.user,
            ad_type=ad_type,
            category_id=category_id,
            title=title,
            description=description,
            price=price if price else None,
            location=location,
            contact_phone=contact_phone,
            contact_email=contact_email,
            contact_telegram=contact_telegram,
        )
        messages.success(request, 'Объявление создано!')
        return redirect('ads_detail', ad_id=ad.id)

    categories = AdCategory.objects.all()
    return render(request, 'website/ads_form.html', {'categories': categories})


@login_required
def ads_respond(request, ad_id):
    """Отклик на объявление"""
    ad = get_object_or_404(Ad, id=ad_id)

    if request.method == 'POST':
        message = request.POST.get('message')
        AdResponse.objects.create(
            ad=ad,
            author=request.user,
            message=message
        )
        messages.success(request, 'Отклик отправлен! Автор объявления свяжется с вами.')
        return redirect('ads_detail', ad_id=ad.id)

    return render(request, 'website/ads_respond.html', {'ad': ad})

@login_required
def ads_edit(request, ad_id):
    """Редактирование объявления"""
    ad = get_object_or_404(Ad, id=ad_id, author=request.user)

    if request.method == 'POST':
        ad.ad_type = request.POST.get('ad_type')
        ad.category_id = request.POST.get('category')
        ad.title = request.POST.get('title')
        ad.description = request.POST.get('description')
        ad.price = request.POST.get('price') or None
        ad.location = request.POST.get('location')
        ad.contact_phone = request.POST.get('contact_phone')
        ad.contact_email = request.POST.get('contact_email')
        ad.contact_telegram = request.POST.get('contact_telegram')
        ad.save()
        messages.success(request, 'Объявление обновлено!')
        return redirect('ads_detail', ad_id=ad.id)

    categories = AdCategory.objects.all()
    return render(request, 'website/ads_form.html', {'ad': ad, 'categories': categories, 'is_edit': True})


@login_required
def ads_delete(request, ad_id):
    """Удаление объявления"""
    ad = get_object_or_404(Ad, id=ad_id, author=request.user)
    ad.delete()
    messages.success(request, 'Объявление удалено!')
    return redirect('ads_list')

@login_required
def ad_responses(request, ad_id):
    """Отклики на моё объявление"""
    ad = get_object_or_404(Ad, id=ad_id, author=request.user)
    responses = ad.responses.all()
    return render(request, 'website/ad_responses.html', {'ad': ad, 'responses': responses})

@login_required
def ads_favorite(request, ad_id):
    """Добавление/удаление из избранного"""
    from website.models import AdFavorite
    ad = get_object_or_404(Ad, id=ad_id)
    fav, created = AdFavorite.objects.get_or_create(user=request.user, ad=ad)
    if not created:
        fav.delete()
    return redirect('ads_detail', ad_id=ad.id)

def rating_stats_api(request):
    from website.models import AnalyticsSettings, AnalyticsMetadata, UpdateLog
    from django.utils import timezone as tz

    drivers = Driver.objects.exclude(rating_score__isnull=True)
    drivers_with_count = drivers.annotate(race_count=Count('raceresult'))

    # Веса контекстной модели
    driver_with_weights = Driver.objects.exclude(context_weights={}).first()
    weights = driver_with_weights.context_weights if driver_with_weights else {}

    # Реальная дата последнего обновления рейтингов
    last_update_str = None
    last_log = UpdateLog.objects.filter(status='success').first()
    if last_log:
        last_update_str = tz.localtime(last_log.updated_at).strftime('%d.%m.%Y %H:%M')

    # Параметры аналитики из БД
    settings = AnalyticsSettings.get()

    data = {
        'total_drivers': drivers.count(),
        'total_races': RaceResult.objects.values('group__page').distinct().count(),
        'low_starts_count': drivers_with_count.filter(race_count__lt=settings.min_starts_display).count(),
        'reliable_count': drivers_with_count.filter(race_count__gte=10).count(),
        'active_classes_count': RaceClass.objects.filter(raceclassresultgroup__isnull=False).distinct().count(),
        'top_drivers': [
            {'name': d.full_name, 'rating': round(d.rating_score, 1)}
            for d in drivers.order_by('-rating_score')[:5]
        ],
        'weights': {
            'precipitation': weights.get('precipitation', 0.00),
            'temperature': weights.get('temperature', 0.00),
            'tyre': weights.get('tyre', 0.00),
        },
        'last_update': last_update_str,
        'settings': {
            'lambda_active': settings.lambda_active,
            'bayes_c': f'{settings.bayes_c:g}',
            'class_transfer_weight': f'{settings.class_transfer_weight * 100:g}',
            'inactive_threshold_days': settings.inactive_threshold_days,
            'min_starts_display': settings.min_starts_display,
            'bt_alpha': settings.bt_alpha,
            'pagerank_damping': settings.pagerank_damping,
            'trend_window': settings.trend_window,
        },
    }
    return JsonResponse(data)


def lap_chart_api(request, group_id):
    """Данные для GriplineLapChart.init() — позиции пилотов по кругам сессии.

    race_number резолвится через RaceResult этой же группы (тот же паттерн,
    что при импорте lap_chart — см. import_utils.py::_build_lap_chart_entries).
    """
    from collections import defaultdict
    from website.models import RaceClassResultGroup, LapPosition

    session_type = request.GET.get('session', 'final')
    if session_type not in ('final', 'pre_final'):
        return JsonResponse({'error': 'invalid session param'}, status=400)

    group = get_object_or_404(RaceClassResultGroup, pk=group_id)

    positions = (
        LapPosition.objects
        .filter(group=group, session_type=session_type)
        .select_related('driver')
        .order_by('driver_id', 'lap')
    )
    if not positions.exists():
        return JsonResponse({'error': 'no lap_chart data for this group/session'}, status=404)

    race_numbers = dict(
        RaceResult.objects
        .filter(group=group, race_number__isnull=False)
        .exclude(race_number='')
        .values_list('driver_id', 'race_number')
    )

    by_driver = defaultdict(dict)
    driver_names = {}
    for p in positions:
        by_driver[p.driver_id][p.lap] = p.position
        driver_names[p.driver_id] = p.driver.full_name

    stages = max(lap for laps in by_driver.values() for lap in laps)
    max_position = max(pos for laps in by_driver.values() for pos in laps.values())

    drivers_payload = []
    for driver_id, laps in by_driver.items():
        num = race_numbers.get(driver_id)
        if num is None:
            continue

        pos_series = [laps.get(i) for i in range(stages + 1)]
        if any(v is None for v in pos_series):
            # Неполная серия (пилот сошёл раньше конца сессии) — виджет ожидает
            # непрерывный массив без дыр, интерполяция pointAt() их не умеет.
            # MVP: такие пилоты не показываются на графике (см. открытый вопрос
            # в ТЗ lap_chart_api — доработка виджета для обрыва линии отдельной
            # задачей, не входит в этот эндпоинт).
            continue

        try:
            num = int(num)
        except (TypeError, ValueError):
            pass

        drivers_payload.append({'num': num, 'name': driver_names[driver_id], 'pos': pos_series})

    drivers_payload.sort(key=lambda d: d['pos'][-1])

    return JsonResponse({'stages': stages, 'maxPosition': max_position, 'drivers': drivers_payload})
