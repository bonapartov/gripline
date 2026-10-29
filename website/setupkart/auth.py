"""Вход в приложение GripLine SetupKart аккаунтом сайта (17.10.2026, план setupkart-account-sync, этап 1).

Вход и регистрация идут обычными страницами сайта в браузере — email, Яндекс, VK, подтверждение email,
заявка пилота работают как на сайте, без второй копии логики в API:

1. Приложение придумывает `verifier`, открывает `auth/start/?challenge=<SHA-256(verifier)>&state=…`.
2. Сайт запоминает challenge в сессии и отправляет на вход (`next` → `auth/complete/`). После входа через
   Яндекс/VK сайт ведёт в ЛК (`SOCIAL_AUTH_LOGIN_REDIRECT_URL`) — оттуда `pending_redirect()` возвращает сюда же.
3. `auth/complete/` выдаёт одноразовый код (3 минуты) и ссылку `gripline-setupkart://login?code=…&state=…`.
4. Приложение меняет код на токен (`auth/exchange/`), предъявив `verifier` (PKCE): перехваченная чужим
   приложением ссылка без `verifier` бесполезна.

Токен — на одно устройство (`AppDeviceToken`), в БД только его хэш. Выход — в приложении или в ЛК.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from wagtailcache.cache import nocache_page

from mysite.security import get_client_ip
from website.models import AppDeviceToken

SESSION_KEY = 'setupkart_login'
PENDING_TTL = 15 * 60
CODE_TTL = 3 * 60
APP_SCHEME = 'gripline-setupkart://login'
TOKEN_PREFIX = 'gsk_'
_B64URL = re.compile(r'^[A-Za-z0-9_-]{43}$')
_STATE = re.compile(r'^[A-Za-z0-9_-]{8,64}$')


def _base_url():
    return getattr(settings, 'BASE_URL', 'https://gripline.ru').rstrip('/')


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def challenge_of(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def _limited(key, limit, window):
    if cache.add(key, 1, window):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:
        cache.set(key, 1, window)
        return False


def _verified(user):
    from accounts.verification import is_email_verified
    return user.is_active and is_email_verified(user)


def _pending(request):
    data = request.session.get(SESSION_KEY)
    if not isinstance(data, dict) or data.get('until', 0) < time.time():
        return None
    return data


def pending_redirect(request):
    """Вход из приложения начат, человек вошёл на сайте (Яндекс/VK ведут в ЛК) — вернуть его в `complete`.
    Пока идёт онбординг Яндекса (выбор роли, пилота) — не мешаем, вернёмся после него."""
    if (request.user.is_authenticated and _pending(request) is not None
            and not request.session.get('yandex_onboarding')):
        return redirect('setupkart_auth_complete')
    return None


def _login_url():
    return reverse('accounts:login') + '?' + urlencode({'next': reverse('setupkart_auth_complete')})


@nocache_page
@require_GET
def start(request):
    challenge = request.GET.get('challenge', '')
    state = request.GET.get('state', '')
    if not _B64URL.match(challenge) or not _STATE.match(state):
        return render(request, 'setupkart/auth_result.html', {'error': 'Ссылка входа неполная. Нажмите «Войти» в приложении ещё раз.'}, status=400)
    request.session[SESSION_KEY] = {'challenge': challenge, 'state': state, 'until': time.time() + PENDING_TTL}
    if request.user.is_authenticated:
        return redirect('setupkart_auth_complete')
    return redirect(_login_url())


@nocache_page
@require_GET
def complete(request):
    if not request.user.is_authenticated:
        return redirect(_login_url())
    pending = _pending(request)
    if pending is None:
        return render(request, 'setupkart/auth_result.html', {
            'error': 'Вход в приложение не начат или устарел. Откройте приложение и нажмите «Войти» ещё раз.'})
    if request.session.get('yandex_onboarding'):
        return redirect('accounts:profile')
    if not _verified(request.user):
        return render(request, 'setupkart/auth_result.html', {
            'error': 'Подтвердите email по ссылке из письма, затем нажмите «Войти» в приложении ещё раз.'})
    del request.session[SESSION_KEY]
    code = secrets.token_urlsafe(32)
    cache.set(f'setupkart:code:{_hash(code)}', {'user': request.user.pk, 'challenge': pending['challenge']}, CODE_TTL)
    link = APP_SCHEME + '?' + urlencode({'code': code, 'state': pending['state']})
    return render(request, 'setupkart/auth_result.html', {'app_link': link})


def _json(request):
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@nocache_page
@csrf_exempt
@require_POST
def exchange(request):
    if _limited(f'setupkart:auth:ip:{get_client_ip(request)}', 30, 3600):
        return JsonResponse({'error': 'rate_limited'}, status=429)
    body = _json(request)
    if body is None:
        return JsonResponse({'error': 'bad_json'}, status=400)
    code = str(body.get('code') or '')
    verifier = str(body.get('verifier') or '')
    key = f'setupkart:code:{_hash(code)}'
    data = cache.get(key) if code else None
    if data is None:
        return JsonResponse({'error': 'bad_code'}, status=400)
    cache.delete(key)  # одноразовый, даже при неверном verifier
    if not (43 <= len(verifier) <= 128) or not hmac.compare_digest(challenge_of(verifier), data['challenge']):
        return JsonResponse({'error': 'bad_code'}, status=400)
    from django.contrib.auth.models import User
    user = User.objects.filter(pk=data['user']).first()
    if user is None or not _verified(user):
        return JsonResponse({'error': 'account_unavailable'}, status=403)
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    AppDeviceToken.objects.create(
        user=user, key_hash=_hash(token), last_used_at=timezone.now(),
        device_name=str(body.get('device') or '')[:120], app_version=str(body.get('app_version') or '')[:40])
    return JsonResponse({'token': token, 'account': account_payload(user)}, json_dumps_params={'ensure_ascii': False})


def token_of(request):
    """Действующий токен из `Authorization: Bearer …` или None."""
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer ' + TOKEN_PREFIX):
        return None
    token = (AppDeviceToken.objects.filter(key_hash=_hash(header[7:].strip()), revoked_at__isnull=True)
             .select_related('user').first())
    if token is None or not _verified(token.user):
        return None
    now = timezone.now()
    if token.last_used_at is None or now - token.last_used_at > timedelta(hours=1):
        AppDeviceToken.objects.filter(pk=token.pk).update(last_used_at=now)
    return token


RATINGS_CACHE_SEC = 600
OUT_REASON_TEXT = {'few_starts': 'вне рейтинга: мало стартов', 'inactive': 'вне рейтинга: давно не выступал'}


def driver_ratings(driver, base):
    """Рейтинг пилота по классам для экрана «Аккаунт» приложения — та же функция, что на странице
    пилота (место, баллы, порядок карточек: текущий класс первым). Расчёт тяжёлый (все пилоты класса),
    поэтому кэш на 10 минут: рейтинг меняется только после пересчёта."""
    key = f'setupkart:ratings:{driver.pk}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    from website.views import _get_driver_class_ratings
    rows = []
    for cr in _get_driver_class_ratings(driver):
        last = cr.get('last_race_date')
        rows.append({
            'class_id': cr['class_id'],
            'class_name': cr['class_name'],
            'score': cr['normalized_score'],
            'rank': None if cr['inactive'] else cr['rank'],
            'total': cr['total'],
            'out_reason': OUT_REASON_TEXT.get(cr['out_reason'] or '', '') if cr['inactive'] else '',
            'starts': cr['starts'],
            'wins': cr['wins'],
            'podiums': cr['podiums'],
            'last_race_date': last.date().isoformat() if hasattr(last, 'date') else (
                last.isoformat() if last else None),
            'url': f"{base}{reverse('top_drivers')}?class={cr['class_id']}",
        })
    cache.set(key, rows, RATINGS_CACHE_SEC)
    return rows


def driver_last_race(driver):
    """Матчасть с последнего этапа пилота по протоколу (29.10.2026): приложение заводит по ней карт —
    класс, шасси, двигатель и шины. Номера класса и двигателя — те же, что в справочнике приложения."""
    from django.db.models import OuterRef, Subquery
    from website.models import EventOccurrence, RaceResult
    r = (RaceResult.objects.filter(driver=driver, group__page__live=True)
         .select_related('group__page', 'group__race_class', 'group__engine', 'group__tyre__brand', 'chassis_new')
         .annotate(event_date=Subquery(EventOccurrence.objects.filter(event_id=OuterRef('group__page_id'))
                                       .order_by('-end').values('end')[:1]))
         .order_by(F('event_date').desc(nulls_last=True), '-group__page__first_published_at').first())
    if r is None:
        return None
    g = r.group
    return {
        'class_id': g.race_class_id,
        'class_name': g.race_class.name,
        'chassis': r.chassis_new.name if r.chassis_new else '',
        'engine_id': g.engine_id,
        'engine': g.engine.name if g.engine else '',
        'tyre_brand': g.tyre.brand.name if g.tyre else '',
        'event': g.page.title,
        'date': r.event_date.date().isoformat() if r.event_date else None,
    }


def account_payload(user):
    """Аккаунт для приложения: имя, привязанный пилот, пилоты команд, которыми он управляет."""
    from accounts.models import DriverClaim
    from teams.models import TeamManager
    from website.models import TeamMembership
    base = _base_url()
    profile = getattr(user, 'profile', None)
    driver = profile.driver if profile is not None and profile.verified and profile.driver_id else None
    teams = list(TeamManager.objects.filter(user=user, is_active=True).select_related('team')
                 .order_by('team__name'))
    team_ids = [m.team_id for m in teams]
    pilots, seen = [], set()
    for m in (TeamMembership.objects.filter(team_id__in=team_ids, is_active=True)
              .select_related('driver', 'team').order_by('driver__last_name', 'driver__first_name')):
        if m.driver_id in seen:
            continue
        seen.add(m.driver_id)
        pilots.append({'id': m.driver_id, 'name': m.driver.full_name, 'team': m.team.name})
    return {
        'email': user.email,
        'name': user.get_full_name() or user.email,
        'driver': ({'id': driver.pk, 'name': driver.full_name, 'url': base + driver.get_absolute_url(),
                    'ratings': driver_ratings(driver, base), 'last_race': driver_last_race(driver)}
                   if driver else None),
        'claim_pending': driver is None and DriverClaim.objects.filter(user=user, status='pending').exists(),
        'teams': [{'id': m.team_id, 'name': m.team.name} for m in teams],
        'team_pilots': pilots,
        'account_url': base + reverse('accounts:profile'),
        'sessions_url': base + reverse('accounts:app_sessions'),
        'delete_url': base + '/legal/data-request/',
    }


def _unauthorized():
    return JsonResponse({'error': 'unauthorized'}, status=401)


@nocache_page
@require_GET
def me(request):
    token = token_of(request)
    if token is None:
        return _unauthorized()
    return JsonResponse({'account': account_payload(token.user)}, json_dumps_params={'ensure_ascii': False})


@nocache_page
@csrf_exempt
@require_POST
def logout(request):
    token = token_of(request)
    if token is None:
        return _unauthorized()
    AppDeviceToken.objects.filter(pk=token.pk).update(revoked_at=timezone.now())
    return JsonResponse({'ok': True})


def devices_for(user):
    """Устройства для ЛК: действующие входы."""
    return AppDeviceToken.objects.filter(user=user, revoked_at__isnull=True)


@nocache_page
@login_required
@require_POST
def revoke_device(request, token_id):
    token = get_object_or_404(AppDeviceToken, pk=token_id, user=request.user)
    if token.revoked_at is None:
        token.revoked_at = timezone.now()
        token.save(update_fields=['revoked_at'])
    return redirect(reverse('accounts:profile') + '#app-devices')
