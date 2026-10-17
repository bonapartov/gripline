"""Аналитика сессий приложения (17.10.2026, этап 4 плана setupkart-account-sync).

Правило старшинства: протокол соревнования главнее данных пилота. Сессия в день этапа на трассе этапа,
у пилота которой есть результат в протоколе, привязывается к этому результату: место и лучший круг берутся
из протокола, круги из приложения остаются «личными». Тренировки (сессии без протокола) никогда не попадают
в рейтинг, рекорды трасс, результаты и статистику пилота — те считаются только по `RaceResult`.
"""
import json
from collections import defaultdict

from django.utils import timezone

from .session_display import PARTS, laptime, profile_sections

TEMP_WINDOW = 5  # «похожая погода»: ±5 °C


def _setup(record):
    raw = record.data.get('setupJson')
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _local_date(record):
    return timezone.localtime(record.started_at).date() if record.started_at else None


def match_events(records):
    """{record.pk: {'event', 'url', 'race_class', 'position', 'status', 'best_ms'}} — сессии в день этапа."""
    from website.models import RaceResult
    wanted = [r for r in records if r.driver_id and r.track_id and r.started_at]
    if not wanted:
        return {}
    drivers = {r.driver_id for r in wanted}
    tracks = {r.track_id for r in wanted}
    results = (RaceResult.objects.filter(driver_id__in=drivers, group__page__track_id__in=tracks,
                                         group__page__live=True)
               .select_related('group__page', 'group__race_class'))
    by_key = defaultdict(list)
    pages = set()
    for res in results:
        by_key[(res.driver_id, res.group.page.track_id)].append(res)
        pages.add(res.group.page_id)
    from website.models import EventOccurrence
    spans = defaultdict(list)
    for occ in EventOccurrence.objects.filter(event_id__in=pages):
        if occ.start:
            end = occ.end or occ.start
            spans[occ.event_id].append((timezone.localtime(occ.start).date(), timezone.localtime(end).date()))
    out = {}
    for r in wanted:
        day = _local_date(r)
        klass = (_setup(r).get('engine_category') or '').strip().lower()
        hits = [res for res in by_key[(r.driver_id, r.track_id)]
                if any(a <= day <= b for a, b in spans[res.group.page_id])]
        if not hits:
            continue
        hit = next((h for h in hits if h.group.race_class.name.strip().lower() == klass), hits[0])
        status = hit.final_status or ''
        out[r.pk] = {
            'event': hit.group.page.title,
            'url': hit.group.page.url,
            'race_class': hit.group.race_class.name,
            'position': hit.position if hit.position and not status else None,
            'status': status,
            'best_ms': hit.best_lap_all_ms,
            'best_text': laptime(hit.best_lap_all_ms),
        }
    return out


def _labels():
    """Подписи числовых полей профиля: {ключ или префикс составного: (подпись, единица)}."""
    from website.models import APP_ENGINE_FIELD_CHOICES
    labels = {}
    for section in profile_sections():
        for f in section['fields']:
            labels[f['key']] = (f['label'], f.get('unit') or '')
    for key, label in APP_ENGINE_FIELD_CHOICES:
        labels.setdefault(key, (label, ''))
    return labels


def label_of(key, labels=None):
    labels = labels or _labels()
    if key in labels:
        return labels[key][0]
    head, _, tail = key.partition('.')
    if head in labels:
        return f"{labels[head][0]} {' '.join(PARTS.get(p, p) for p in tail.split('.'))}"
    return key


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(',', '.'))
        except ValueError:
            return None
    return None


SKIP_KEYS = {'best_time_ms', 'laps', 'driver_id', 'run_start_ms', 'run_end_ms', 'lap_marks_ms', 'engine_minutes'}


def points(rows, events):
    """Точки сессий: время (протокол, если есть, иначе своё) + числовые параметры сетапа."""
    out = []
    for row in rows:
        r = row['record']
        ev = events.get(r.pk)
        best = (ev or {}).get('best_ms') or r.data.get('bestTimeMs')
        if not isinstance(best, (int, float)) or best <= 0:
            continue
        setup = _setup(r)
        params = {}
        for k, v in setup.items():
            if k in SKIP_KEYS:
                continue
            n = _number(v)
            if n is not None:
                params[k] = n
        if isinstance(r.data.get('dayTempC'), (int, float)):
            params.setdefault('day_temp_c', float(r.data['dayTempC']))
        out.append({'row': row, 'best': int(best), 'best_text': laptime(best),
                    'official': bool(ev and ev.get('best_ms')), 'params': params})
    return out


def numeric_params(pts, minimum=3):
    """Параметры, которые есть хотя бы в [minimum] сессиях и меняются — для оси X графика."""
    counts, values = defaultdict(int), defaultdict(set)
    for p in pts:
        for k, v in p['params'].items():
            counts[k] += 1
            values[k].add(v)
    labels = _labels()
    keys = [k for k in counts if counts[k] >= minimum and len(values[k]) > 1]
    return sorted(((k, label_of(k, labels)) for k in keys), key=lambda x: x[1])


def scatter(pts, key):
    return [{'x': p['params'][key], 'y': round(p['best'] / 1000, 3), 'official': p['official'],
             'name': p['row']['name'] or '', 'date': p['row']['date'].strftime('%d.%m.%Y') if p['row']['date'] else '',
             'uuid': p['row']['record'].uuid}
            for p in pts if key in p['params']]


def best_sessions(pts, temp=None):
    """Лучшая сессия на каждой трассе; с [temp] — среди сессий с температурой в пределах ±5 °C."""
    best = {}
    for p in pts:
        if temp is not None:
            t = p['params'].get('day_temp_c')
            if t is None or abs(t - temp) > TEMP_WINDOW:
                continue
        key = p['row']['track'] or '—'
        if key not in best or p['best'] < best[key]['best']:
            best[key] = p
    return sorted(best.values(), key=lambda p: p['row']['track'])


def changes(pts, limit=10):
    """Соседние сессии одного дня на одной трассе и одном карте: что поменяли и как изменилось время."""
    labels = _labels()
    groups = defaultdict(list)
    for p in pts:
        row = p['row']
        if row['date']:
            groups[(row['date'].date(), row['track'], row['kart_key'])].append(p)
    out = []
    for items in groups.values():
        items.sort(key=lambda p: p['row']['date'])
        for a, b in zip(items, items[1:]):
            sa, sb = _setup(a['row']['record']), _setup(b['row']['record'])
            diff = []
            for k in sorted(set(sa) | set(sb)):
                if k in SKIP_KEYS or isinstance(sa.get(k), (dict, list)) or isinstance(sb.get(k), (dict, list)):
                    continue
                if sa.get(k) != sb.get(k) and k not in ('track', 'track_id', 'driver'):
                    diff.append((label_of(k, labels), sa.get(k, '—'), sb.get(k, '—')))
            delta = (b['best'] - a['best']) / 1000
            out.append({'a': a, 'b': b, 'diff': diff, 'delta': delta, 'when': b['row']['date']})
    out.sort(key=lambda c: c['when'], reverse=True)
    return out[:limit]


def compare_rows(setup_a, setup_b):
    """Сравнение двух сессий: [(подпись, значение A, значение B, отличается)]."""
    labels = _labels()
    keys = sorted((set(setup_a) | set(setup_b)) - SKIP_KEYS - {'track_id'}, key=lambda k: label_of(k, labels))
    rows = []
    for k in keys:
        a, b = setup_a.get(k), setup_b.get(k)
        if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
            continue
        if a in (None, '') and b in (None, ''):
            continue
        rows.append((label_of(k, labels), '' if a is None else a, '' if b is None else b, a != b))
    rows.sort(key=lambda r: (not r[3], r[0]))
    return rows


__all__ = ['match_events', 'points', 'numeric_params', 'scatter', 'best_sessions', 'changes', 'compare_rows',
           'laptime', 'label_of']
