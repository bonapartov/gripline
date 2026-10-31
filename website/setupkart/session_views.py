"""Сессии из приложения в ЛК пилота и ЛК команды (17.10.2026, этап 2 плана setupkart-account-sync).

Видимость: владелец видит все свои сессии. Менеджер команды — сессии пилотов активного состава своих
команд, если пилот (владелец сессии) не выключил «Видны команде» в целом и у этой сессии. «На странице
пилота» хранится уже сейчас, показ на публичной странице — этап 4.

Все сессии из приложения — личные данные (плашка «Тр»): протоколы соревнований выше по статусу, в рейтинг,
рекорды и результаты они не попадают.
"""
import json
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from wagtailcache.cache import nocache_page

from website.models import AppSyncRecord

from . import analytics
from .public import purge_driver_page
from .session_display import laps_summary, laptime, sections


def _setup(record):
    raw = record.data.get('setupJson')
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _managed_driver_ids(user):
    from teams.access import managed_driver_ids
    return managed_driver_ids(user)


def _sessions():
    return (AppSyncRecord.objects.filter(table='sessions', deleted=False)
            .select_related('track', 'driver', 'user', 'user__profile'))


def team_sessions_qs(user):
    drivers = _managed_driver_ids(user)
    return _sessions().filter(driver_id__in=drivers).filter(
        Q(user=user) | Q(visible_to_team=True, user__profile__app_sessions_team=True))


def can_view(user, record):
    if record.user_id == user.pk:
        return True
    return team_sessions_qs(user).filter(pk=record.pk).exists()


def _names(user_ids, table):
    return {(r.user_id, r.uuid): r.data.get('name') or ''
            for r in AppSyncRecord.objects.filter(user_id__in=user_ids, table=table)}


def _rows(records):
    records = list(records)
    users = {r.user_id for r in records}
    karts, engines = _names(users, 'karts'), _names(users, 'engines')
    events = analytics.match_events(records)
    rows = []
    for r in records:
        setup = _setup(r)
        rows.append({
            'event': events.get(r.pk),
            'record': r,
            'date': timezone.localtime(r.started_at) if r.started_at else None,
            'name': r.data.get('name') or '',
            'track': r.track.name if r.track else (setup.get('track') or ''),
            'track_key': f't{r.track_id}' if r.track_id else (f"n:{setup.get('track')}" if setup.get('track') else ''),
            'kart': karts.get((r.user_id, r.data.get('kartId')), ''),
            'kart_key': r.data.get('kartId') or '',
            'engine': engines.get((r.user_id, r.data.get('engineId')), ''),
            'pilot': r.driver.full_name if r.driver else (setup.get('driver') or ''),
            'race_class': setup.get('engine_category') or '',
            'best': laptime(r.data.get('bestTimeMs')),
            'laps': laps_summary(setup),
        })
    return rows


def _filter(rows, request):
    track, kart, klass = request.GET.get('track', ''), request.GET.get('kart', ''), request.GET.get('class', '')
    try:
        since = date.fromisoformat(request.GET.get('from', ''))
    except ValueError:
        since = None
    try:
        until = date.fromisoformat(request.GET.get('to', ''))
    except ValueError:
        until = None
    options = {
        'tracks': sorted({(r['track_key'], r['track']) for r in rows if r['track_key']}, key=lambda x: x[1]),
        'karts': sorted({(r['kart_key'], r['kart']) for r in rows if r['kart_key'] and r['kart']}, key=lambda x: x[1]),
        'classes': sorted({r['race_class'] for r in rows if r['race_class']}),
    }
    out = [r for r in rows
           if (not track or r['track_key'] == track) and (not kart or r['kart_key'] == kart)
           and (not klass or r['race_class'] == klass)
           and (not since or (r['date'] and r['date'].date() >= since))
           and (not until or (r['date'] and r['date'].date() <= until))]
    return out, options


def _ordered(qs):
    return qs.order_by('-started_at', '-pk')


@nocache_page
@login_required
def my_sessions(request):
    profile = getattr(request.user, 'profile', None)
    if request.method == 'POST' and profile is not None:
        profile.app_sessions_team = request.POST.get('team') == '1'
        profile.app_sessions_public = request.POST.get('public') == '1'
        profile.save(update_fields=['app_sessions_team', 'app_sessions_public'])
        purge_driver_page(profile.driver)
        return redirect('accounts:app_sessions')
    rows, options = _filter(_rows(_ordered(_sessions().filter(user=request.user))), request)
    return render(request, 'setupkart/sessions_list.html', {
        'mode': 'own', 'rows': rows, 'options': options, 'profile': profile, 'q': request.GET,
    })


@nocache_page
@login_required
def team_sessions(request):
    if not _managed_driver_ids(request.user) and not request.user.team_managers.filter(is_active=True).exists():
        raise Http404
    rows, options = _filter(_rows(_ordered(team_sessions_qs(request.user))), request)
    return render(request, 'setupkart/sessions_list.html', {
        'mode': 'team', 'rows': rows, 'options': options, 'q': request.GET,
    })


@nocache_page
@login_required
def session_detail(request, uuid):
    record = _sessions().filter(uuid=uuid).filter(
        Q(user=request.user) | Q(pk__in=team_sessions_qs(request.user).values('pk'))).first()
    if record is None:
        raise Http404
    own = record.user_id == request.user.pk
    row = _rows([record])[0]
    setup = _setup(record)
    return render(request, 'setupkart/session_detail.html', {
        'row': row, 'record': record, 'own': own, 'sections': sections(setup),
        'profile': getattr(request.user, 'profile', None), 'notes': setup.get('notes') or '',
    })


@nocache_page
@login_required
@require_POST
def session_visibility(request, uuid):
    record = _sessions().filter(uuid=uuid, user=request.user).first()
    if record is None:
        raise Http404
    record.visible_to_team = request.POST.get('team') == '1'
    record.public = request.POST.get('public') == '1'
    record.save(update_fields=['visible_to_team', 'public'])
    purge_driver_page(record.driver)
    return redirect('accounts:app_session', uuid=uuid)


def _visible_qs(user):
    return _sessions().filter(Q(user=user) | Q(pk__in=team_sessions_qs(user).values('pk')))


@nocache_page
@login_required
def sessions_analytics(request):
    """Аналитика своих сессий: время круга от параметра, лучшие сессии, «что меняли → что дало»."""
    rows, options = _filter(_rows(_ordered(_sessions().filter(user=request.user))), request)
    events = {row['record'].pk: row['event'] for row in rows if row['event']}
    pts = analytics.points(rows, events)
    params = analytics.numeric_params(pts)
    keys = [k for k, _ in params]
    x = request.GET.get('x') or next((k for k in ('day_temp_c', 'main_jet', 'pressure.fl.cold') if k in keys),
                                     keys[0] if keys else '')
    try:
        temp = float(request.GET.get('temp', '').replace(',', '.'))
    except ValueError:
        temp = None
    return render(request, 'setupkart/sessions_analytics.html', {
        'options': options, 'q': request.GET, 'params': params, 'x': x,
        'x_label': analytics.label_of(x) if x else '',
        'scatter': analytics.scatter(pts, x) if x in keys else [],
        'best': analytics.best_sessions(pts), 'best_temp': analytics.best_sessions(pts, temp) if temp is not None else None,
        'temp': temp, 'changes': analytics.changes(pts), 'count': len(pts),
    })


@nocache_page
@login_required
def sessions_compare(request):
    qs = _visible_qs(request.user)
    a = qs.filter(uuid=request.GET.get('a', '')).first()
    b = qs.filter(uuid=request.GET.get('b', '')).first()
    choices = _rows(_ordered(_sessions().filter(user=request.user))[:300])
    ctx = {'choices': choices, 'q': request.GET}
    if a and b:
        ra, rb = _rows([a, b])
        ctx.update({'a': ra, 'b': rb, 'rows': analytics.compare_rows(_setup(a), _setup(b))})
    return render(request, 'setupkart/sessions_compare.html', ctx)
