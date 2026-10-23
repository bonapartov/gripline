"""Данные страницы трассы по классам: рекорды, секторы, статистика.

Одна строка RaceResult = один пилот на одном этапе в одном классе, все
сессии (квалификация, предфинал, финал) внутри неё (см. CLAUDE.md →
«Поля RaceResult»). «Старт» — строка RaceResult, «победа» — position=1.

load_rows() читает БД, остальное — чистые функции над списком строк
(тесты: website/tests/test_track_stats.py).
"""
import datetime
import statistics
from collections import defaultdict

SESSIONS = (
    # ключ, подпись, поле круга, поля секторов, поле статуса
    ('qual', 'квалификация', 'qual_best_lap_ms', ('qual_s1_ms', 'qual_s2_ms', 'qual_s3_ms'), 'qual_status'),
    ('pre_final', 'предфинал', 'pre_final_best_lap_ms',
     ('pre_final_s1_ms', 'pre_final_s2_ms', 'pre_final_s3_ms'), 'pre_final_status'),
    ('final', 'финал', 'best_lap_ms', ('best_s1_ms', 'best_s2_ms', 'best_s3_ms'), 'final_status'),
)
SESSION_LABELS = {key: label for key, label, *_ in SESSIONS}
LEADERS_LIMIT = 5


def load_rows(track):
    """Строки результатов этой трассы (только опубликованные этапы) в виде простых dict."""
    from website.models import RaceResult

    results = (RaceResult.objects
               .filter(group__page__track=track, group__page__live=True)
               .select_related('driver', 'group__race_class', 'group__page')
               .prefetch_related('group__page__occurrences'))
    page_dates = {}
    rows = []
    for r in results:
        page = r.group.page
        if page.id not in page_dates:
            occ = sorted(page.occurrences.all(), key=lambda o: o.start)
            page_dates[page.id] = occ[0].start.date() if occ and occ[0].start else None
        sessions = {}
        for key, _label, lap_f, sec_f, status_f in SESSIONS:
            # Дисквалификация в сессии — её круг и секторы в рекорды не идут
            if getattr(r, status_f) == 'DQ':
                continue
            sessions[key] = {
                'lap': getattr(r, lap_f) or None,
                'sec': [getattr(r, f) or None for f in sec_f],
            }
        rc = r.group.race_class
        rows.append({
            'class_id': rc.id,
            'class_name': rc.name,
            'class_order': (rc.sort_order, rc.name),
            'driver_id': r.driver_id,
            'driver_name': r.driver.full_name,
            'driver_url': r.driver.get_absolute_url(),
            'event_id': page.id,
            'event_url': page.url,
            'date': page_dates[page.id],
            'position': r.position,
            'sessions': sessions,
        })
    return rows


def _holder(row, session, value_ms):
    return {
        'ms': value_ms,
        'driver_name': row['driver_name'],
        'driver_url': row['driver_url'],
        'session': session,
        'session_label': SESSION_LABELS[session],
        'date': row['date'],
        'event_url': row['event_url'],
    }


def _date_key(row):
    return row['date'] or datetime.date.max


def best_lap(rows):
    """Лучший круг по всем сессиям; при равенстве — показанный раньше."""
    best = None
    for row in rows:
        for key, s in row['sessions'].items():
            lap = s['lap']
            if lap and (best is None or (lap, _date_key(row)) < (best[0], _date_key(best[1]))):
                best = (lap, row, key)
    return _holder(best[1], best[2], best[0]) if best else None


def best_sectors(rows):
    """[держатель S1, S2, S3] — минимум каждого сектора по всем сессиям; None, где данных нет."""
    out = []
    for k in range(3):
        best = None
        for row in rows:
            for key, s in row['sessions'].items():
                v = s['sec'][k]
                if v and (best is None or (v, _date_key(row)) < (best[0], _date_key(best[1]))):
                    best = (v, row, key)
        out.append(_holder(best[1], best[2], best[0]) if best else None)
    return out


def has_full_sectors(rows):
    return any(all(s['sec']) for row in rows for s in row['sessions'].values())


def field_medians(rows):
    """Медиана поля по каждому сектору — на последнем этапе класса, где есть секторы:
    у каждого пилота его лучший сектор за этап (по всем сессиям), затем медиана по пилотам."""
    by_event = defaultdict(list)
    for row in rows:
        by_event[row['event_id']].append(row)
    events = [ev for ev in by_event.values() if has_full_sectors(ev)]
    if not events:
        return [None, None, None]
    last = max(events, key=lambda ev: (ev[0]['date'] or datetime.date.min, ev[0]['event_id']))
    out = []
    for k in range(3):
        per_driver = {}
        for row in last:
            vals = [s['sec'][k] for s in row['sessions'].values() if s['sec'][k]]
            if vals:
                d = row['driver_id']
                per_driver[d] = min(vals + ([per_driver[d]] if d in per_driver else []))
        out.append(round(statistics.median(per_driver.values())) if per_driver else None)
    return out


def leaders(rows, limit=LEADERS_LIMIT):
    stats = {}
    for row in rows:
        st = stats.setdefault(row['driver_id'], {
            'driver_name': row['driver_name'], 'driver_url': row['driver_url'],
            'starts': 0, 'wins': 0, 'podiums': 0,
        })
        st['starts'] += 1
        pos = row['position'] or 0
        if pos == 1:
            st['wins'] += 1
        if 1 <= pos <= 3:
            st['podiums'] += 1
    ranked = sorted(stats.values(), key=lambda s: (-s['wins'], -s['podiums'], -s['starts'], s['driver_name']))
    return ranked[:limit]


def races_by_year(rows, years):
    """[{year, races, drivers}] по всем годам трассы (years), включая годы без этого класса."""
    races, drivers = defaultdict(set), defaultdict(set)
    for row in rows:
        if row['date']:
            races[row['date'].year].add(row['event_id'])
            drivers[row['date'].year].add(row['driver_id'])
    return [{'year': y, 'races': len(races[y]), 'drivers': len(drivers[y])} for y in years]


def record_history(rows):
    """По годам, новые сверху: лучший круг класса за год и улучшение к предыдущему году (мс, > 0 — быстрее)."""
    by_year = defaultdict(list)
    for row in rows:
        if row['date']:
            by_year[row['date'].year].append(row)
    hist = []
    prev = None
    for year in sorted(by_year):
        rec = best_lap(by_year[year])
        if not rec:
            continue
        delta = (prev - rec['ms']) if prev is not None else None
        rec = {**rec, 'year': year, 'delta_ms': delta,
               # «−0.286» — быстрее прошлогоднего рекорда, «+0.120» — медленнее, «—» — первый год
               'delta_text': '—' if delta is None else (f'−{delta / 1000:.3f}' if delta > 0 else f'+{-delta / 1000:.3f}')}
        prev = rec['ms']
        hist.append(rec)
    return list(reversed(hist))


def class_data(rows, years):
    rec = best_lap(rows)
    sectors = best_sectors(rows)
    sectors_ok = has_full_sectors(rows) and all(sectors)
    data = {
        'id': rows[0]['class_id'],
        'name': rows[0]['class_name'],
        'order': rows[0]['class_order'],
        'starts': len(rows),
        'record': rec,
        'has_sectors': sectors_ok,
        'sectors': [],
        'ideal_ms': None,
        'gap_ms': None,
        'years': races_by_year(rows, years),
        'leaders': leaders(rows),
        'history': record_history(rows),
    }
    if sectors_ok:
        ideal = sum(s['ms'] for s in sectors)
        medians = field_medians(rows)
        data['ideal_ms'] = ideal
        if rec and rec['ms'] > ideal:
            data['gap_ms'] = rec['ms'] - ideal
        data['sectors'] = [
            {**s, 'index': k, 'name': f'S{k + 1}', 'share': f"{s['ms'] / ideal * 100:.1f}", 'median_ms': medians[k],
             'turns': ''}
            for k, s in enumerate(sectors)
        ]
    max_drivers = max((y['drivers'] for y in data['years']), default=0) or 1
    for y in data['years']:
        y['height'] = max(2, round(y['drivers'] / max_drivers * 110)) if y['drivers'] else 2
    return data


def build_track_classes(rows):
    """Классы трассы (только ехавшие), порядок — по регламенту (RaceClass.sort_order)."""
    years = sorted({r['date'].year for r in rows if r['date']})
    by_class = defaultdict(list)
    for row in rows:
        by_class[row['class_id']].append(row)
    classes = [class_data(class_rows, years) for class_rows in by_class.values()]
    classes.sort(key=lambda c: c['order'])
    return classes


def default_class(classes):
    """Самый массовый класс; при равенстве — первый по регламенту."""
    if not classes:
        return None
    # max() берёт первый из равных — classes уже отсортированы по регламенту
    return max(classes, key=lambda c: c['starts'])


def absolute_record(classes):
    best = None
    for c in classes:
        if c['record'] and (best is None or c['record']['ms'] < best['record']['ms']):
            best = c
    return {'ms': best['record']['ms'], 'class_name': best['name']} if best else None
