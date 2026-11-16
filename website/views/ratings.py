"""Расчёт рейтинга пилотов: сглаживание, места, статистика и рекорды."""

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
def _compute_form_trend(driver_id, class_id, window=None):
    """
    Сравнивает последние N гонок с предыдущими N по нормализованной позиции.
    Возвращает 'up', 'down', 'stable' или None (мало данных).
    N берётся из AnalyticsSettings.trend_window.
    """
    from django.db.models import Count
    from website.models import AnalyticsSettings

    if window is None:
        window = AnalyticsSettings.get().trend_window

    rows = list(
        RaceResult.objects.filter(
            driver_id=driver_id,
            group__race_class_id=class_id,
        )
        .annotate(group_size=Count('group__class_results'))
        .order_by('group__page__first_published_at')
        .values('position', 'group_size')
    )

    if len(rows) < window + 1:
        return None

    def norm(pos, total):
        return (total - pos) / (total - 1) * 100 if total > 1 else 50.0

    recent = rows[-window:]
    previous = rows[-(2 * window):-window]

    if not previous:
        return None

    avg_recent = sum(norm(r['position'], r['group_size']) for r in recent) / len(recent)
    avg_prev = sum(norm(r['position'], r['group_size']) for r in previous) / len(previous)

    diff = avg_recent - avg_prev
    if diff > 10:
        return 'up'
    elif diff < -10:
        return 'down'
    return 'stable'


def _rating_inactive(entry, threshold_days):
    """Пилот не выступал в классе дольше порога — в таблице рейтинга его нет."""
    from datetime import date as _date
    last = entry.get('last_race_date')
    if not last:
        return False
    try:
        return (_date.today() - _date.fromisoformat(last)).days > threshold_days
    except (ValueError, TypeError):
        return False


MIN_PILOTS_FOR_STARTS_RULE = 5


def class_min_starts(class_key, drivers, settings):
    """Порог стартов для таблицы класса. Действует, только если его набрали хотя бы
    MIN_PILOTS_FOR_STARTS_RULE активных пилотов: в небольших классах (Микро, 4Т, E-10…)
    у всех по 1–2 старта, и таблица иначе опустела бы — там показываются все."""
    import json
    need = settings.min_starts_display
    enough = 0
    for d in drivers:
        rbc = d.rating_by_class or {}
        if isinstance(rbc, str):
            try:
                rbc = json.loads(rbc)
            except Exception:
                rbc = {}
        entry = rbc.get(str(class_key))
        if (entry and int(entry.get('starts', 0) or 0) >= need
                and not _rating_inactive(entry, settings.inactive_threshold_days)):
            enough += 1
            if enough >= MIN_PILOTS_FOR_STARTS_RULE:
                return need
    return 0


def rating_out_reason(entry, settings, min_starts):
    """Почему пилота нет в таблице рейтинга класса: 'inactive' (давно не выступал),
    'few_starts' (меньше [min_starts] стартов — см. class_min_starts) или None.
    Одно правило для таблицы /top/drivers/, главной, страницы пилота и сравнения."""
    if _rating_inactive(entry, settings.inactive_threshold_days):
        return 'inactive'
    if int(entry.get('starts', 0) or 0) < min_starts:
        return 'few_starts'
    return None


def _quantile(sorted_scores, pct):
    """Значение на доле pct (0 — худший, 1 — лучший) отсортированного списка, с интерполяцией."""
    if len(sorted_scores) == 1:
        return sorted_scores[0]
    pos = max(0.0, min(1.0, pct)) * (len(sorted_scores) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_scores) - 1)
    return sorted_scores[lo] + (sorted_scores[hi] - sorted_scores[lo]) * (pos - lo)


class ClassSmoother:
    """Байесовское сглаживание рейтинга в классе: (N × BT + C × опора) / (N + C).

    Опора — медиана класса. У пилота, перешедшего из другого класса (update_ratings
    кладёт в рейтинг 'prior_pct' — его место в прошлом классе, 0 — последний, 1 — первый),
    опора сдвинута от медианы к тому же месту нового класса на долю class_transfer_weight
    (18.10.2026: лидер Mini в Junior начинает выше середины, а не с неё).
    Одна формула для таблицы, главной, страницы пилота и сравнения.
    """

    def __init__(self, scores, settings):
        import statistics as _stats
        self.sorted = sorted(scores)
        self.mu = _stats.median(self.sorted) if self.sorted else 0.0
        self.C = settings.bayes_c
        self.weight = settings.class_transfer_weight

    def prior(self, entry):
        pct = (entry or {}).get('prior_pct')
        if pct is None or not self.weight or not self.sorted:
            return self.mu
        return self.mu + self.weight * (_quantile(self.sorted, float(pct)) - self.mu)

    def smooth(self, bt_score, starts, entry):
        return (starts * bt_score + self.C * self.prior(entry)) / (starts + self.C)


def _class_ranking_entries(class_id, all_drivers, keep_driver_id=None):
    """Полный отсортированный рейтинг пилотов в классе — Байесовское сглаживание
    (C из AnalyticsSettings.bayes_c, та же формула, что и top_drivers_view). Используется и
    _get_driver_class_ratings (место/соседи/немезис текущего пилота), и
    _nearby_class_rivals (вкладка «Соперники»).

    Выборка — как в таблице /top/drivers/ (rating_out_reason): не участвуют пилоты,
    не выступавшие в классе дольше inactive_threshold_days, и пилоты с числом стартов
    меньше min_starts_display (иначе медиана и места расходились с таблицей:
    18.10.2026 — №4 в таблице, №5 на странице пилота). Если [keep_driver_id] сам
    вне таблицы, он возвращается отдельной записью с `inactive=True`, `out_reason`
    и местом, которое занял бы; места остальных от этого не меняются.
    """
    import json
    from website.models import AnalyticsSettings

    class_id_str = str(class_id)
    settings = AnalyticsSettings.get()
    all_drivers = list(all_drivers)
    min_starts = class_min_starts(class_id, all_drivers, settings)

    entries = []
    extra = None
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
        item = {
            'driver': d,
            'driver_id': d.id,
            'full_name': f"{d.first_name} {d.last_name}".strip(),
            'slug': d.slug,
            'bt_score': float(entry.get('score', 0.0)),
            'starts': int(entry.get('starts', 0)),
            'entry': entry,
            'inactive': False,
            'out_reason': None,
        }
        reason = rating_out_reason(entry, settings, min_starts)
        if reason:
            if d.id == keep_driver_id:
                item['inactive'] = True
                item['out_reason'] = reason
                extra = item
            continue
        entries.append(item)
    if not entries:
        return [extra] if extra else []

    smoother = ClassSmoother([e['bt_score'] for e in entries], settings)

    def smooth(e):
        return smoother.smooth(e['bt_score'], e['starts'], e['entry'])

    for e in entries:
        e['smoothed'] = smooth(e)
    entries.sort(key=lambda x: x['smoothed'], reverse=True)

    min_s = min(e['smoothed'] for e in entries)
    max_s = max(e['smoothed'] for e in entries)
    rng = max_s - min_s if max_s != min_s else 1.0
    total = len(entries)
    for i, e in enumerate(entries):
        e['rank'] = i + 1
        e['total'] = total
        e['normalized'] = round((e['smoothed'] - min_s) / rng * 100, 1)
    if extra:
        extra['smoothed'] = smooth(extra)
        extra['rank'] = sum(1 for e in entries if e['smoothed'] > extra['smoothed']) + 1
        extra['total'] = total
        extra['normalized'] = round(min(100.0, max(0.0, (extra['smoothed'] - min_s) / rng * 100)), 1)
        entries.append(extra)
    return entries


def _nearby_class_rivals(driver, class_id, count=5):
    """5 ближайших по месту в рейтинге пилотов в этом классе (не считая самого
    пилота) — блок «Соперники» на странице пилота. Тот же _class_ranking_entries,
    что и _get_driver_class_ratings — места совпадают с тем, что уже показано
    в карточках рейтинга. Победы/подиумы/поулы — сырые счётчики в этом классе,
    для сравнения карточек соперников (та же идея, что у карточек соперников
    driverdb.com — не только место/рейтинг, но и достижения)."""
    all_drivers = (
        Driver.objects.exclude(rating_by_class={})
        .only('id', 'first_name', 'last_name', 'slug', 'photo', 'city', 'rating_by_class')
    )
    entries = _class_ranking_entries(class_id, all_drivers, keep_driver_id=driver.id)
    if not entries:
        return []

    target = next((e for e in entries if e['driver_id'] == driver.id), None)
    if target is None:
        return []

    others = [e for e in entries if e is not target]
    others.sort(key=lambda e: abs(e['rank'] - target['rank']))
    nearby = sorted(others[:count], key=lambda e: e['rank'])

    nearby_ids = [e['driver_id'] for e in nearby]
    raw = RaceResult.objects.filter(
        driver_id__in=nearby_ids, group__race_class_id=class_id
    ).values('driver_id').annotate(
        wins=Count('id', filter=Q(position=1)),
        podiums=Count('id', filter=Q(position__in=[1, 2, 3])),
        poles=Count('id', filter=Q(qual_position=1)),
    )
    by_driver = {r['driver_id']: r for r in raw}

    return [{
        'driver': e['driver'],
        'rank': e['rank'],
        'total': e['total'],
        'normalized_score': e['normalized'],
        'starts': e['starts'],
        'wins': by_driver.get(e['driver_id'], {}).get('wins', 0),
        'podiums': by_driver.get(e['driver_id'], {}).get('podiums', 0),
        'poles': by_driver.get(e['driver_id'], {}).get('poles', 0),
    } for e in nearby]


def _class_stat_percentiles(driver, class_id):
    """Перцентили И сырые счётчики пилота внутри класса — общий источник для
    радара «Профиль результатов» (нужны только *_pct + rating_pct) и тайлов
    Обзора в режиме «Класс» (нужны ещё и сырые значения, и Финиши/DNF).
    Выборка сравнения — пилоты с BT-рейтингом в этом классе (уже
    ≥ AnalyticsSettings.min_races_per_class стартов — та же выборка, что и
    _class_ranking_entries). Рейтинг — перцентиль места в том же списке
    rank/total, что и в карточках рейтинга (не пересчитывается по-другому).
    Возвращает None, если сравнивать не с кем (< 2 пилотов с рейтингом в классе).
    """
    all_drivers = (
        Driver.objects.exclude(rating_by_class={})
        .only('id', 'first_name', 'last_name', 'slug', 'rating_by_class')
    )
    entries = _class_ranking_entries(class_id, all_drivers, keep_driver_id=driver.id)
    if not entries:
        return None

    target = next((e for e in entries if e['driver_id'] == driver.id), None)
    if target is None:
        return None

    total = target['total']
    if total < 2:
        return None

    peer_ids = [e['driver_id'] for e in entries]
    raw = RaceResult.objects.filter(
        driver_id__in=peer_ids, group__race_class_id=class_id
    ).values('driver_id').annotate(
        starts=Count('id'),
        wins=Count('id', filter=Q(position=1)),
        podiums=Count('id', filter=Q(position__in=[1, 2, 3])),
        poles=Count('id', filter=Q(qual_position=1)),
        dnf=Count('id', filter=Q(final_status__in=['DNF', 'DQ'])),
    )
    by_driver = {r['driver_id']: r for r in raw}
    my = by_driver.get(driver.id, {'starts': 0, 'wins': 0, 'podiums': 0, 'poles': 0, 'dnf': 0})
    my_finished = my['starts'] - my['dnf']
    my_dnf_ratio = round(my['dnf'] / my['starts'] * 100, 1) if my['starts'] else 0

    def vals(metric):
        return [by_driver.get(pid, {}).get(metric, 0) for pid in peer_ids]

    def percentile(values, my_value, higher_is_better=True):
        if higher_is_better:
            better = sum(1 for v in values if v < my_value)
        else:
            better = sum(1 for v in values if v > my_value)
        return round(better / (total - 1) * 100, 1)

    finished_vals = [
        by_driver.get(pid, {}).get('starts', 0) - by_driver.get(pid, {}).get('dnf', 0)
        for pid in peer_ids
    ]
    dnf_ratio_vals = [
        round(by_driver.get(pid, {}).get('dnf', 0) / by_driver.get(pid, {}).get('starts', 0) * 100, 1)
        if by_driver.get(pid, {}).get('starts', 0) else 0
        for pid in peer_ids
    ]

    rating_pct = round((total - target['rank']) / (total - 1) * 100, 1)

    return {
        'peer_count': total,
        'rating_pct': rating_pct,
        'starts': my['starts'],
        'starts_pct': percentile(vals('starts'), my['starts']),
        'finished': my_finished,
        'finished_pct': percentile(finished_vals, my_finished),
        'dnf_ratio': my_dnf_ratio,
        'dnf_ratio_pct': percentile(dnf_ratio_vals, my_dnf_ratio, higher_is_better=False),
        'wins': my['wins'],
        'wins_pct': percentile(vals('wins'), my['wins']),
        'podiums': my['podiums'],
        'podiums_pct': percentile(vals('podiums'), my['podiums']),
        'poles': my['poles'],
        'poles_pct': percentile(vals('poles'), my['poles']),
    }


def _career_stat_percentiles(driver, total_starts, wins, podiums, poles, finished, dnf_ratio):
    """Перцентили карьерных счётчиков («лучше, чем N% пилотов») для тайлов
    Обзора — среди ВСЕХ пилотов сайта (по всем классам сразу, как и сами эти
    счётчики), а не только текущего класса. Порог входа в выборку — тот же
    AnalyticsSettings.min_races_per_class, что и для BT-рейтинга по классам
    (не отдельная настройка — одна ручка «сколько стартов достаточно, чтобы
    считаться»). Возвращает None, если у самого пилота стартов меньше порога —
    тайлы просто не покажут подпись (сами счётчики при этом видны всегда).
    DNF ratio — обратное направление: меньше значит лучше.
    """
    from website.models import AnalyticsSettings

    threshold = AnalyticsSettings.get().min_races_per_class
    if total_starts < threshold:
        return None

    totals = list(
        RaceResult.objects.values('driver_id').annotate(
            starts=Count('id'),
            wins=Count('id', filter=Q(position=1)),
            podiums=Count('id', filter=Q(position__in=[1, 2, 3])),
            poles=Count('id', filter=Q(qual_position=1)),
            dnf=Count('id', filter=Q(final_status__in=['DNF', 'DQ'])),
        ).filter(starts__gte=threshold)
    )
    if len(totals) < 2:
        return None

    n = len(totals)
    finished_vals = [row['starts'] - row['dnf'] for row in totals]
    dnf_ratio_vals = [
        round(row['dnf'] / row['starts'] * 100, 1) if row['starts'] else 0 for row in totals
    ]

    def percentile(values, my_value, higher_is_better=True):
        if higher_is_better:
            better = sum(1 for v in values if v < my_value)
        else:
            better = sum(1 for v in values if v > my_value)
        return round(better / (n - 1) * 100, 1)

    return {
        'peer_count': n,
        'starts': percentile([row['starts'] for row in totals], total_starts),
        'wins': percentile([row['wins'] for row in totals], wins),
        'podiums': percentile([row['podiums'] for row in totals], podiums),
        'poles': percentile([row['poles'] for row in totals], poles),
        'finished': percentile(finished_vals, finished),
        'dnf_ratio': percentile(dnf_ratio_vals, dnf_ratio, higher_is_better=False),
    }


def _get_driver_class_ratings(driver):
    """
    Returns per-class rating context for a driver profile page:
    rank, total, normalized BT score (0-100), form trend, gaps to neighbours.
    Uses same Bayesian smoothing (AnalyticsSettings.bayes_c) as top_drivers_view.
    """
    import json, statistics as _stats
    from datetime import datetime, timezone as dt_timezone

    rbc = driver.rating_by_class or {}
    if isinstance(rbc, str):
        try:
            rbc = json.loads(rbc)
        except Exception:
            rbc = {}
    if not rbc:
        return []

    all_drivers = list(
        Driver.objects.exclude(rating_by_class={})
        .only('id', 'first_name', 'last_name', 'slug', 'rating_by_class')
    )

    class_ratings = []

    for class_id_str in rbc.keys():
        class_id = int(class_id_str)

        class_entries = _class_ranking_entries(class_id, all_drivers, keep_driver_id=driver.id)
        if not class_entries:
            continue

        target = next((e for e in class_entries if e['driver_id'] == driver.id), None)
        if target is None:
            continue

        total = target['total']
        rank = target['rank']
        # Соседи — среди остальных пилотов (для неактивного пилота — вокруг места,
        # которое он занял бы).
        pool = [e for e in class_entries if e is not target]
        driver_above = pool[rank - 2] if rank > 1 else None
        driver_below = pool[rank - 1] if rank - 1 < len(pool) else None
        gap_to_above = round(driver_above['normalized'] - target['normalized'], 1) if driver_above else None
        gap_to_below = round(target['normalized'] - driver_below['normalized'], 1) if driver_below else None

        try:
            class_name = RaceClass.objects.get(id=class_id).name
        except RaceClass.DoesNotExist:
            class_name = f'Класс {class_id}'

        class_qs = RaceResult.objects.filter(driver=driver, group__race_class_id=class_id)
        starts = target['starts']
        wins_in_class = class_qs.filter(position=1).count()
        podiums_in_class = class_qs.filter(position__in=[1, 2, 3]).count()
        win_pct = round(wins_in_class / starts * 100, 1) if starts > 0 else 0
        podium_pct = round(podiums_in_class / starts * 100, 1) if starts > 0 else 0

        # --- Медианы класса для инсайтов ---
        all_class_results = list(RaceResult.objects.filter(
            group__race_class_id=class_id
        ).values('driver_id', 'position'))
        class_driver_stats = {}
        for r in all_class_results:
            d = class_driver_stats.setdefault(r['driver_id'], {'starts': 0, 'wins': 0, 'podiums': 0})
            d['starts'] += 1
            if r['position'] == 1: d['wins'] += 1
            if r['position'] <= 3: d['podiums'] += 1
        win_pcts_all = [s['wins']/s['starts']*100 for s in class_driver_stats.values() if s['starts'] >= 3]
        podium_pcts_all = [s['podiums']/s['starts']*100 for s in class_driver_stats.values() if s['starts'] >= 3]
        median_win_pct = round(_stats.median(win_pcts_all), 1) if win_pcts_all else 0
        median_podium_pct = round(_stats.median(podium_pcts_all), 1) if podium_pcts_all else 0

        # --- Немезис и жертва ---
        driver_group_ids = set(class_qs.values_list('group_id', flat=True))
        driver_positions = {r['group_id']: r['position'] for r in class_qs.values('group_id', 'position')}
        other_results = RaceResult.objects.filter(
            group_id__in=driver_group_ids,
            group__race_class_id=class_id,
        ).exclude(driver=driver).select_related('driver').values(
            'driver_id', 'driver__first_name', 'driver__last_name', 'driver__slug', 'group_id', 'position'
        )
        opp_stats = {}
        for r in other_results:
            oid = r['driver_id']
            if oid not in opp_stats:
                opp_stats[oid] = {
                    'name': f"{r['driver__first_name']} {r['driver__last_name']}".strip(),
                    'slug': r['driver__slug'],
                    'meetings': 0, 'wins': 0, 'losses': 0,
                }
            my_pos = driver_positions.get(r['group_id'])
            if my_pos is None:
                continue
            opp_stats[oid]['meetings'] += 1
            if my_pos < r['position']:
                opp_stats[oid]['wins'] += 1
            elif my_pos > r['position']:
                opp_stats[oid]['losses'] += 1
        qualified = {k: v for k, v in opp_stats.items() if v['meetings'] >= 3}
        nemesis = max(qualified.values(), key=lambda x: x['losses'], default=None)
        if nemesis and nemesis['losses'] <= nemesis['wins']:
            nemesis = None  # не настоящий немезис если чаще побеждаем
        victim = max(qualified.values(), key=lambda x: x['wins'], default=None)
        if victim and victim['wins'] <= victim['losses']:
            victim = None  # не настоящая жертва если чаще проигрываем

        last_result = class_qs.annotate(
            event_end=Subquery(
                EventOccurrence.objects.filter(
                    event_id=OuterRef('group__page_id')
                ).order_by('-end').values('end')[:1]
            )
        ).order_by('-event_end', '-group__page__last_published_at').first()
        if last_result:
            last_race_date = getattr(last_result, 'event_end', None) or last_result.group.page.last_published_at
        else:
            last_race_date = None

        class_ratings.append({
            'class_id': class_id,
            'class_name': class_name,
            'rank': rank,
            'inactive': target['inactive'],
            'out_reason': target['out_reason'],
            'total': total,
            'normalized_score': target['normalized'],
            'starts': starts,
            'wins': wins_in_class,
            'podiums': podiums_in_class,
            'win_pct': win_pct,
            'podium_pct': podium_pct,
            'low_data': starts < 3,
            'races_left': max(3 - starts, 0),
            'last_race_date': last_race_date,
            'form_trend': _compute_form_trend(driver.id, class_id),
            'gap_to_above': gap_to_above,
            'gap_to_below': gap_to_below,
            'driver_above': driver_above,
            'driver_below': driver_below,
            'median_win_pct': median_win_pct,
            'median_podium_pct': median_podium_pct,
            'nemesis': nemesis,
            'victim': victim,
        })

    # Текущий класс (последний старт — самый свежий) всегда первым, за ним —
    # остальные классы в хронологическом порядке (по дате последнего старта
    # в каждом, от самого раннего к позднему). Не алфавит и не сортировка
    # по class_id — пилот видит сначала то, чем занят сейчас, потом историю.
    # last_race_date может быть None (нет ни occurrence, ни last_published_at
    # ни у одного результата класса) — такой класс считаем самым старым.
    _epoch = datetime.min.replace(tzinfo=dt_timezone.utc)
    class_ratings.sort(key=lambda x: x['last_race_date'] or _epoch)
    if class_ratings:
        current_idx = max(
            range(len(class_ratings)),
            key=lambda i: class_ratings[i]['last_race_date'] or _epoch,
        )
        class_ratings.insert(0, class_ratings.pop(current_idx))
    return class_ratings


def _compute_all_track_records():
    """Тяжёлая версия — считает рекорды трасс вживую по ВСЕМ трассам и классам
    сразу (не на одного пилота). Не вызывать на каждый рендер страницы — см.
    _get_driver_track_records() и команду update_track_records.

    Возвращает {track_id: {class_id_str: {'final_holder_id', 'record_year',
    'lap_ms', 'ever_holder_ids', 'result_id', 'record_date'}}}; result_id —
    RaceResult действующего рекорда (подробности для приложения SetupKart).
    """
    from collections import defaultdict

    from website.services.race_results import published_results, result_datetime
    all_results = published_results().select_related(
        'driver', 'group__race_class', 'group__page'
    ).prefetch_related('group__page__occurrences')

    by_key = defaultdict(list)
    for r in all_results:
        lap = r.best_lap_all_ms
        if not lap:
            continue
        event = r.group.page
        track = getattr(event, 'track', None)
        if not track:
            continue
        event_date = result_datetime(event)
        if not event_date:
            continue
        by_key[(track.id, r.group.race_class_id)].append({
            'date': event_date,
            'driver_id': r.driver_id,
            'lap_ms': lap,
            'result_id': r.pk,
        })

    result = defaultdict(dict)
    for (track_id, class_id), entries in by_key.items():
        entries.sort(key=lambda e: e['date'])

        running_min = None
        final_holder_id = None
        record_year = None
        record_entry = None
        ever_holder_ids = []

        for e in entries:
            if running_min is None or e['lap_ms'] < running_min:
                running_min = e['lap_ms']
                final_holder_id = e['driver_id']
                record_year = e['date'].year
                record_entry = e
                if e['driver_id'] not in ever_holder_ids:
                    ever_holder_ids.append(e['driver_id'])

        result[track_id][str(class_id)] = {
            'final_holder_id': final_holder_id,
            'record_year': record_year,
            'lap_ms': running_min,
            'ever_holder_ids': ever_holder_ids,
            'result_id': record_entry['result_id'],
            'record_date': record_entry['date'].date().isoformat() if hasattr(record_entry['date'], 'date')
            else record_entry['date'].isoformat(),
        }

    return result


def _compute_driver_track_records_live(driver):
    """Фильтрует _compute_all_track_records() на одного пилота. Fallback-путь
    для _get_driver_track_records(), пока команда update_track_records ни разу
    не запускалась (Track.records_cache везде пуст) — тяжёлая версия, считает
    всё вживую на каждый вызов."""
    from website.models import Driver

    all_records = _compute_all_track_records()
    current_year = timezone.now().year
    records = []

    track_ids = list(all_records.keys())
    tracks = {t.id: t for t in Track.objects.filter(id__in=track_ids)}
    class_ids = {int(cid) for classes in all_records.values() for cid in classes.keys()}
    race_classes = {c.id: c for c in RaceClass.objects.filter(id__in=class_ids)}

    for track_id, classes in all_records.items():
        for class_id_str, data in classes.items():
            if driver.id not in data['ever_holder_ids']:
                continue
            records.append(_track_record_row(
                tracks[track_id], race_classes[int(class_id_str)], data, driver, current_year
            ))

    status_order = {'active': 0, 'locked': 1, 'beaten': 2}
    records.sort(key=lambda r: (status_order[r['status']], -r['year']))
    return records


def _track_record_row(track, race_class, data, driver, current_year):
    """Собирает одну строку «Рекорды трасс» из данных кэша (или живого расчёта)."""
    final_holder_id = data['final_holder_id']
    record_year = data['record_year']
    row = {
        'track': track,
        'class_name': race_class.name,
        'lap_ms': data['lap_ms'],
        'year': record_year,
    }
    if final_holder_id == driver.id:
        row['status'] = 'active' if record_year == current_year else 'locked'
    else:
        row['status'] = 'beaten'
        holder = Driver.objects.filter(id=final_holder_id).first()
        row['holder_name'] = holder.full_name if holder else '—'
    return row


def _get_driver_track_records(driver):
    """Рекорды трасс пилота: по каждой паре (трасса, класс), где пилот когда-либо
    держал рекорд круга, определяет статус — действующий/закреплён/перебит.
    Рекорд принадлежит тому, кто когда-либо показал новый минимум круга в
    классе на трассе; статус — календарный год, в котором установлен ТЕКУЩИЙ
    рекорд (не год, когда его показал именно этот пилот, если рекорд с тех
    пор перебивали).

    Читает из Track.records_cache (обновляется командой update_track_records,
    запускается вручную после ввода новых результатов — как update_ratings).
    Раньше пересчитывалось вживую при каждом вызове — перебор ВСЕХ RaceResult
    сайта на каждый рендер страницы пилота, самая тяжёлая часть страницы
    (~1.2с из ~1.5с общего времени, профайлер 27.08.2026). Если ни одна трасса
    ещё не закэширована (до первого запуска команды) — fallback на живой
    расчёт через _compute_driver_track_records_live(), поведение не ломается.
    """
    current_year = timezone.now().year
    tracks = list(Track.objects.exclude(records_cache={}))

    if not tracks:
        return _compute_driver_track_records_live(driver)

    class_ids = {
        int(cid)
        for track in tracks
        for cid, data in track.records_cache.items()
        if driver.id in data['ever_holder_ids']
    }
    race_classes = {c.id: c for c in RaceClass.objects.filter(id__in=class_ids)}

    records = []
    for track in tracks:
        for class_id_str, data in track.records_cache.items():
            if driver.id not in data['ever_holder_ids']:
                continue
            records.append(_track_record_row(
                track, race_classes[int(class_id_str)], data, driver, current_year
            ))

    status_order = {'active': 0, 'locked': 1, 'beaten': 2}
    records.sort(key=lambda r: (status_order[r['status']], -r['year']))
    return records


def _get_driver_best_title(driver):
    """Самый свежий титул пилота (1-е место в классе по итогам сезона).

    None, если пилот никогда не был чемпионом. Переиспользуется страницей
    пилота (Career highlights) и медиа-китом (website/services/mediakit.py).
    """
    from website.models import ChampionshipPage

    best_title = None
    for champ in ChampionshipPage.objects.live():
        for year in champ.get_years():
            champions_by_class = champ.get_champions_by_class(year)
            for class_id, data in champions_by_class.items():
                if not data['champions']:
                    continue
                winner = data['champions'][0]
                if winner['driver'].id == driver.id:
                    if best_title is None or year > best_title['year']:
                        best_title = {
                            'championship': champ,
                            'year': year,
                            'class_name': data['name'],
                        }
    return best_title


def _get_driver_career_highlights(driver, results, wins, podiums, total_starts, podium_percentage):
    """Собирает 4 бейджа Career highlights для страницы пилота.

    Возвращает [] если данных нет вообще (блок не рендерится).
    """
    highlights = {}

    best_title = _get_driver_best_title(driver)
    if best_title:
        highlights['title'] = best_title

    # --- Лучший результат: лучшая позиция за карьеру + счётчик побед ---
    non_dnf = [r for r in results if r.final_status != 'DNF' and r.final_status != 'DQ']
    if non_dnf:
        best_position = min(r.position for r in non_dnf)
        recent_best = max(
            (r for r in non_dnf if r.position == best_position),
            key=lambda r: getattr(r, 'event_date', None) or r.group.page.last_published_at or r.group.page.first_published_at,
        )
        highlights['best_result'] = {
            'position': best_position,
            'wins': wins,
            'result': recent_best,
        }

    # --- Личный лучший круг за карьеру ---
    lap_results = [r for r in results if r.best_lap_all_ms]
    if lap_results:
        best_lap_result = min(lap_results, key=lambda r: r.best_lap_all_ms)
        event = best_lap_result.group.page
        has_lap_chart = bool(
            best_lap_result.race_number
            and best_lap_result.race_number in best_lap_result.group.lap_chart_race_numbers()
        )
        highlights['best_lap'] = {
            'lap_ms': best_lap_result.best_lap_all_ms,
            'track': getattr(event, 'track', None),
            'class_name': best_lap_result.group.race_class.name,
            'result': best_lap_result,
            'has_lap_chart': has_lap_chart,
        }

    # --- Подиумы: накопительный счётчик + доля от стартов ---
    if total_starts > 0:
        highlights['podiums'] = {
            'count': podiums,
            'percentage': podium_percentage,
        }

    return highlights


def top_drivers_view(request):
    """
    Страница с топ-пилотами (главный рейтинг — Bradley-Terry с байесовским сглаживанием).
    """
    import json
    import statistics
    from datetime import date, timedelta

    current_site = Site.find_for_request(request)

    from website.models import Driver, RaceClass, RaceResult, AnalyticsSettings

    all_classes = [
        c for c in RaceClass.objects.for_site()
        if Driver.objects.filter(rating_by_class__has_key=str(c.id)).exists()
    ]
    classes = list(all_classes)

    # Подсветка конкретной строки — переход со страницы пилота (пилюля
    # «Рейтинг · <класс>»), не влияет на выбор класса/сортировку.
    highlight_slug = request.GET.get('highlight') or ''

    selected_class_id = request.GET.get('class')
    if selected_class_id and selected_class_id.isdigit():
        selected_class_id = int(selected_class_id)
    else:
        selected_class_id = classes[0].id if classes else None

    analytics_settings = AnalyticsSettings.get()

    # Пилоты с BT-рейтингом (чистый Bradley-Terry, без PageRank)
    drivers = list(Driver.objects.exclude(rating_by_class={}).order_by('last_name'))
    min_starts = (class_min_starts(selected_class_id, drivers, analytics_settings)
                  if selected_class_id else 0)

    result_drivers = []

    for driver in drivers:
        if not selected_class_id:
            continue

        class_key = str(selected_class_id)
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
        if rating_out_reason(bt_data, analytics_settings, min_starts):
            continue

        bt_score = bt_data.get('score', 0)
        starts = bt_data.get('starts', 0)

        results = RaceResult.objects.filter(
            driver=driver,
            group__race_class_id=selected_class_id,
        )
        race_count = results.count()
        win_count = results.filter(position=1).count()
        podium_count = results.filter(position__in=[1, 2, 3]).count()
        win_percentage = round(win_count / race_count * 100, 1) if race_count > 0 else 0

        driver.race_count = race_count
        driver.win_count = win_count
        driver.podium_count = podium_count
        driver.win_percentage = win_percentage
        driver.bt_score = bt_score
        driver.starts_in_class = starts
        driver._rating_entry = bt_data

        result_drivers.append(driver)

    from website.seo_meta import rating_seo

    selected_class = next((c for c in classes if c.id == selected_class_id), None)
    is_default_class = bool(classes) and selected_class_id == classes[0].id

    if not result_drivers:
        return render(request, "coderedcms/snippets/top_drivers_page.html", {
            "seo": rating_seo(current_site, race_class=selected_class, is_default=is_default_class),
            "selected_class": selected_class,
            "drivers": [],
            "classes": classes,
            "selected_class_id": selected_class_id,
            "highlight_slug": highlight_slug,
            "site": current_site,
            "page": None,
            "feedback_source": ("rating", selected_class_id),
        })

    # Байесовское сглаживание: новичков тянет к медиане класса или к их уровню
    # в прошлом классе (ClassSmoother)
    smoother = ClassSmoother([d.bt_score for d in result_drivers], AnalyticsSettings.get())
    for driver in result_drivers:
        driver.smoothed_score = smoother.smooth(driver.bt_score, driver.starts_in_class, driver._rating_entry)

    # Сортировка и места
    result_drivers.sort(key=lambda x: x.smoothed_score, reverse=True)
    for idx, driver in enumerate(result_drivers, 1):
        driver.rank = idx

    # Нормировка 0–100
    min_s = result_drivers[-1].smoothed_score
    max_s = result_drivers[0].smoothed_score
    rng = max_s - min_s if max_s > min_s else 1
    for driver in result_drivers:
        driver.normalized_rating = round((driver.smoothed_score - min_s) / rng * 100, 1)

    # Тренд формы (▲ / ▬ / ▼)
    for driver in result_drivers:
        driver.form_trend = _compute_form_trend(driver.id, selected_class_id)

    return render(request, "coderedcms/snippets/top_drivers_page.html", {
        "seo": rating_seo(current_site, race_class=selected_class, drivers_count=len(result_drivers),
                          leader=result_drivers[0], is_default=is_default_class),
        "selected_class": selected_class,
        "drivers": result_drivers,
        "classes": classes,
        "selected_class_id": selected_class_id,
        "highlight_slug": highlight_slug,
        "site": current_site,
        "page": None,
        "feedback_source": ("rating", selected_class_id),  # виджет «Обратная связь»
    })
