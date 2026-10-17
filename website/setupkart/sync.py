"""Синхронизация карт, двигателей, трасс и сессий приложения с сайтом (17.10.2026, этап 2 плана
setupkart-account-sync).

Телефон присылает строки своей БД как есть (drift `toJson()`), сайт хранит их по UUID и отдаёт другим
телефонам того же аккаунта. Правило конфликта — новее по `updatedAt` побеждает, прежняя версия сохраняется
(`AppSyncRecordVersion`). Черновики не синхронизируются. Фото на этом этапе не передаются.

Пилот сессии на сайте (`AppSyncRecord.driver`) — по `driver_id` из снимка сетапа, только если это сам
пользователь (подтверждённый пилот) или пилот активного состава команды, которой он управляет. Иначе —
пусто: в ЛК сессия видна только владельцу.
"""
import json
from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from wagtailcache.cache import nocache_page

from website.models import APP_SYNC_TABLES, AppSyncRecord, AppSyncRecordVersion, Track

from .auth import _limited, _unauthorized, token_of

MAX_BODY = 5 * 1024 * 1024
MAX_ROWS = 500
MAX_RECORDS = 20000
MAX_ROW_BYTES = 256 * 1024
PULL_LIMIT = 500


def allowed_driver_ids(user):
    """Пилоты, которых пользователь может указать в своих сессиях."""
    from teams.models import TeamManager
    from website.models import TeamMembership
    ids = set()
    profile = getattr(user, 'profile', None)
    if profile is not None and profile.verified and profile.driver_id:
        ids.add(profile.driver_id)
    teams = TeamManager.objects.filter(user=user, is_active=True).values_list('team_id', flat=True)
    ids.update(TeamMembership.objects.filter(team_id__in=list(teams), is_active=True)
               .values_list('driver_id', flat=True))
    return ids


def _ms(value):
    """DateTime drift: миллисекунды (по умолчанию) или ISO-строка."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _setup(row):
    raw = row.get('setupJson')
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _session_fields(record, row, drivers, track_bases):
    setup = _setup(row)
    driver_id = setup.get('driver_id')
    record.driver_id = driver_id if isinstance(driver_id, int) and driver_id in drivers else None
    base = track_bases.get(row.get('trackId'))
    record.track_id = base if base and Track.objects.filter(pk=base).exists() else None
    started = _ms(row.get('startedAt'))
    record.started_at = (datetime.fromtimestamp(started / 1000, tz=dt_timezone.utc) if started else None)


def _cursor(record):
    return f'{record.server_updated_at.isoformat()}|{record.pk}'


@nocache_page
@csrf_exempt
@require_POST
def push(request):
    token = token_of(request)
    if token is None:
        return _unauthorized()
    user = token.user
    if _limited(f'setupkart:sync:push:{user.pk}', 240, 3600):
        return JsonResponse({'error': 'rate_limited'}, status=429)
    if len(request.body) > MAX_BODY:
        return JsonResponse({'error': 'too_large'}, status=413)
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'error': 'bad_json'}, status=400)
    tables = body.get('tables') if isinstance(body, dict) else None
    schema = body.get('schema_version') if isinstance(body, dict) else None
    if not isinstance(tables, dict) or not isinstance(schema, int):
        return JsonResponse({'error': 'bad_request'}, status=400)
    rows = [(t, r) for t in APP_SYNC_TABLES for r in (tables.get(t) or []) if isinstance(r, dict)]
    if len(rows) > MAX_ROWS:
        return JsonResponse({'error': 'too_many'}, status=413)
    existing_count = AppSyncRecord.objects.filter(user=user).count()

    drivers = allowed_driver_ids(user)
    accepted = skipped = 0
    with transaction.atomic():
        now = timezone.now()
        for table, row in rows:
            uuid = row.get('id')
            updated = _ms(row.get('updatedAt'))
            if not isinstance(uuid, str) or not (1 <= len(uuid) <= 64) or updated is None:
                skipped += 1
                continue
            if table == 'sessions' and row.get('isDraft'):
                skipped += 1
                continue
            if len(json.dumps(row, ensure_ascii=False)) > MAX_ROW_BYTES:
                skipped += 1
                continue
            record = (AppSyncRecord.objects.select_for_update()
                      .filter(user=user, table=table, uuid=uuid).first())
            if record is None:
                if existing_count >= MAX_RECORDS:
                    skipped += 1
                    continue
                existing_count += 1
                record = AppSyncRecord(user=user, table=table, uuid=uuid)
            elif record.client_updated_at > updated or (record.client_updated_at == updated and record.data == row):
                # Время в приложении — с точностью до секунды: правка в ту же секунду с другим содержимым
                # принимается, повтор того же — нет.
                skipped += 1
                continue
            else:
                AppSyncRecordVersion.objects.create(record=record, data=record.data,
                                                    client_updated_at=record.client_updated_at)
                old = list(record.versions.values_list('pk', flat=True)[AppSyncRecordVersion.KEEP:])
                if old:
                    AppSyncRecordVersion.objects.filter(pk__in=old).delete()
            record.data = row
            record.schema_version = schema
            record.client_updated_at = updated
            record.deleted = row.get('deletedAt') is not None
            record.server_updated_at = now
            if table == 'sessions':
                track_ids = [row.get('trackId')] if row.get('trackId') else []
                bases = {r.uuid: r.data.get('baseId') for r in AppSyncRecord.objects.filter(
                    user=user, table='tracks', uuid__in=track_ids)}
                _session_fields(record, row, drivers, bases)
            record.save()
            accepted += 1
    return JsonResponse({'accepted': accepted, 'skipped': skipped})


@nocache_page
@require_GET
def pull(request):
    token = token_of(request)
    if token is None:
        return _unauthorized()
    user = token.user
    if _limited(f'setupkart:sync:pull:{user.pk}', 600, 3600):
        return JsonResponse({'error': 'rate_limited'}, status=429)
    qs = AppSyncRecord.objects.filter(user=user)
    since = request.GET.get('since', '')
    if since:
        try:
            ts, pk = since.rsplit('|', 1)
            ts = datetime.fromisoformat(ts)
            pk = int(pk)
        except ValueError:
            return JsonResponse({'error': 'bad_since'}, status=400)
        from django.db.models import Q
        qs = qs.filter(Q(server_updated_at__gt=ts) | Q(server_updated_at=ts, pk__gt=pk))
    records = list(qs.order_by('server_updated_at', 'pk')[:PULL_LIMIT + 1])
    more = len(records) > PULL_LIMIT
    records = records[:PULL_LIMIT]
    tables = {t: [] for t in APP_SYNC_TABLES}
    for r in records:
        tables[r.table].append({'schema_version': r.schema_version, 'row': r.data})
    return JsonResponse({
        'tables': tables,
        'cursor': _cursor(records[-1]) if records else since,
        'more': more,
    }, json_dumps_params={'ensure_ascii': False})
