"""API для мобильного приложения GripLine SetupKart (ТЗ приложения §13.1, §13.3, §13.4).

Без авторизации: справочники и трассы — только чтение, предложения — анонимно и с ограничением частоты.
`@nocache_page` обязателен: глобальный wagtailcache иначе отдавал бы старую версию справочника.
"""
import hashlib
import json
import logging

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from wagtailcache.cache import nocache_page

from mysite.security import get_client_ip
from website.models import (
    APP_ENGINE_FIELD_CHOICES, APP_PARAMETER_CHOICES, AppSuggestion, AppSyncSettings, Engine, Track,
)
from .catalog import latest_version

logger = logging.getLogger(__name__)

SUGGESTION_FIELDS = (
    {k for k, _ in APP_ENGINE_FIELD_CHOICES} | {k for k, _ in APP_PARAMETER_CHOICES}
    | {'spark_plug', 'tyre_make', 'chassis', 'engine', 'race_class', 'track'}
)
MAX_VALUE_LEN = 60


def _limited(key, limit, window):
    """True — лимит исчерпан. Счётчик в кэше на окно `window` секунд."""
    added = cache.add(key, 1, window)
    if added:
        return False
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        return False
    return count > limit


@nocache_page
@require_GET
def catalog(request):
    last = latest_version()
    if last is None:
        return JsonResponse({'error': 'not_published'}, status=404)
    since = request.GET.get('since')
    if since and since.isdigit() and int(since) >= last.version:
        return JsonResponse({'version': last.version, 'unchanged': True})
    return JsonResponse(last.payload, json_dumps_params={'ensure_ascii': False})


def tracks_payload():
    tracks = (Track.objects.filter(show_in_app=True, live=True, latitude__isnull=False, longitude__isnull=False)
              .order_by('name'))
    items = [{'id': t.pk, 'name': t.name, 'city': t.city or '', 'region': t.region or '',
              'latitude': t.latitude, 'longitude': t.longitude} for t in tracks]
    version = hashlib.sha1(json.dumps(items, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    return {'version': version, 'tracks': items}


@nocache_page
@require_GET
def tracks(request):
    data = tracks_payload()
    if request.GET.get('since') == data['version']:
        return JsonResponse({'version': data['version'], 'unchanged': True})
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


@nocache_page
@csrf_exempt
@require_POST
def suggestions(request):
    ip = get_client_ip(request)
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'error': 'bad_json'}, status=400)
    client_id = str(body.get('client_id') or '')[:64]
    if _limited(f'setupkart:sugg:ip:{ip}', 60, 3600) or (
            client_id and _limited(f'setupkart:sugg:cid:{client_id}', 30, 86400)):
        return JsonResponse({'error': 'rate_limited'}, status=429)

    field_key = str(body.get('field_key') or '').strip()
    value = ' '.join(str(body.get('value') or '').split())
    if field_key not in SUGGESTION_FIELDS or not value or len(value) > MAX_VALUE_LEN:
        return JsonResponse({'error': 'invalid'}, status=400)
    lat = lon = None
    if field_key == 'track':
        # Своя трасса пользователя: название + координаты обязательны.
        try:
            lat, lon = float(body.get('latitude')), float(body.get('longitude'))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'invalid'}, status=400)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return JsonResponse({'error': 'invalid'}, status=400)
    engine = None
    engine_id = body.get('engine_id')
    if engine_id not in (None, ''):
        engine = Engine.objects.filter(pk=engine_id, show_in_app=True).first()
        if engine is None:
            return JsonResponse({'error': 'unknown_engine'}, status=400)

    obj, created = AppSuggestion.objects.get_or_create(
        field_key=field_key, engine=engine, value=value, defaults={'latitude': lat, 'longitude': lon})
    if not created:
        AppSuggestion.objects.filter(pk=obj.pk).update(count=F('count') + 1, last_seen=timezone.now())
    return JsonResponse({'ok': True}, status=201 if created else 200)


@nocache_page
def config(request):
    """Настройки связи для приложения: интервал задаётся в админке («Приложение» → «Связь с сайтом»)."""
    s = AppSyncSettings.get()
    return JsonResponse({'sync_interval_minutes': s.sync_interval_minutes, 'about': s.about_payload()})


@nocache_page
@csrf_exempt
@require_POST
def feedback(request):
    """Обратная связь из приложения → бот (своя тема) + письмо администратору (ТЗ приложения §13.2)."""
    from website.feedback import service
    from .feedback import CATEGORY_LABELS, TEXT_MAX, create_app_feedback, notify_admins

    ip = get_client_ip(request)
    if _limited(f'setupkart:fb:ip:{ip}', 10, 3600):
        return JsonResponse({'error': 'rate_limited'}, status=429)
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'error': 'bad_json'}, status=400)

    client_id = str(body.get('client_id') or '').strip()[:64]
    kind = str(body.get('category') or '')
    text = str(body.get('text') or '').strip()
    email = str(body.get('contact_email') or '').strip()[:254]
    if not client_id or kind not in CATEGORY_LABELS or not text or len(text) > TEXT_MAX:
        return JsonResponse({'error': 'invalid'}, status=400)
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({'error': 'invalid_email'}, status=400)
        if body.get('consent') is not True:
            return JsonResponse({'error': 'consent_required'}, status=400)

    user = service.get_or_create_user('setupkart', client_id)
    if user.is_banned or service.is_rate_limited(user):
        return JsonResponse({'error': 'rate_limited'}, status=429)

    fb = create_app_feedback(
        client_id=client_id, kind=kind, text=text, contact_email=email,
        app_version=str(body.get('app_version') or '')[:40], device_info=str(body.get('device_info') or '')[:120],
    )
    transaction.on_commit(lambda: notify_admins(fb, email))
    return JsonResponse({'ok': True, 'number': fb.pk}, status=201)
