"""Схема трассы: геометрия осевой линии и SVG для страницы трассы и PDF.

Источник — Track.scheme_data, его пишет редактор схемы в админке
(website/track_scheme_views.py). SVG строится здесь, на сервере, из
проверенных чисел — в Track.scheme_svg никогда не попадает разметка из
браузера, так что схема не может принести на сайт скрипт.

Линия — замкнутый сплайн через опорные точки (по направлению движения),
каждый отрезок — кубическая кривая Безье. По умолчанию — центростремительный
Catmull-Rom (alpha = 0.5): на неравномерных точках (OpenStreetMap) обычный
даёт петли в шпильках (ТЗ, доп. №1, Д2). Для деления на секторы кривая
дискретизируется в ломаную (SAMPLES_PER_SEGMENT точек на отрезок), отметки
«старт» / «S1|S2» / «S2|S3» — доли длины этой ломаной от первой опорной
точки. Та же геометрия повторена в website/static/website/js/track_scheme_geom.js
(редактор и 3D) — при правке менять оба места, тест test_track_scheme.py
сверяет их через Node.

Поле схемы — ширина 640, высота по форме трассы (240–480, доп. №1, Д3);
толщина полотна — track_width_m в масштабе схемы (Д5).
"""
import math

VIEW_W = 640
VIEW_H_MIN, VIEW_H_MAX = 240, 480
LEGACY_VIEW_H = 400
SAMPLES_PER_SEGMENT = 20
SCHEME_VERSION = 1

MAX_POINTS = 1000
MAX_TURNS = 80
MARK_TOLERANCE = 3  # насколько *_xy может отстоять от линии (единицы схемы)
DEFAULT_TRACK_WIDTH_M = 9.0
FALLBACK_STROKE = 30  # толщина полотна, если масштаб неизвестен (нет ни scale_m_per_unit, ни длины трассы)

INTERPOLATIONS = ('centripetal-catmull-rom', 'catmull-rom')
PROVISIONAL_KEYS = ('start', 's1s2', 's2s3', 'track_width_m', 'turns', 'direction')
PROVISIONAL_LABELS = {
    'start': 'Старт/финиш', 's1s2': 'Граница S1|S2', 's2s3': 'Граница S2|S3',
    'track_width_m': 'Ширина полотна', 'turns': 'Повороты', 'direction': 'Направление движения',
}

# Цвета секторов: экран (тёмная тема сайта) и печать (тёмные варианты — светлый лист, ч/б)
SECTOR_COLORS = ('#ffc107', '#0dcaf0', '#28a745')
SECTOR_TEXT = ('#1a1a25', '#1a1a25', '#ffffff')
PRINT_SECTOR_COLORS = ('#e0a800', '#0a8fb0', '#1e7e34')

PALETTES = {
    'screen': {
        'track': '#2a2a35', 'track_inner': None, 'sectors': SECTOR_COLORS,
        'turn_fill': '#15151c', 'turn_stroke': '#eceff1', 'turn_text': '#ffffff',
        'label_text': '#adb5bd', 'arrow': '#ffffff', 'checker_dark': '#0d0d15', 'checker_stroke': None,
    },
    'print': {
        'track': '#1a1a25', 'track_inner': '#e4e4e8', 'sectors': PRINT_SECTOR_COLORS,
        'turn_fill': '#ffffff', 'turn_stroke': '#1a1a25', 'turn_text': '#1a1a25',
        'label_text': '#1a1a25', 'arrow': '#1a1a25', 'checker_dark': '#1a1a25', 'checker_stroke': '#1a1a25',
    },
}


class SchemeError(ValueError):
    """Данные схемы из редактора не прошли проверку."""


# ── Геометрия ────────────────────────────────────────────────────────────

def bezier_segments(points, tension=1.0, interpolation='catmull-rom'):
    """Замкнутый сплайн → список кубических Безье (p0, c1, c2, p1).
    tension — «Плавность» редактора: 0 — ломаная, 1 — сплайн как есть."""
    n = len(points)
    segs = []
    for i in range(n):
        p0, p1 = points[i - 1], points[i]
        p2, p3 = points[(i + 1) % n], points[(i + 2) % n]
        if interpolation == 'centripetal-catmull-rom':
            # alpha = 0.5: «длины» узлов — корни расстояний; d² = расстояние
            e1 = max(math.hypot(p1[0] - p0[0], p1[1] - p0[1]), 1e-9)
            e2 = max(math.hypot(p2[0] - p1[0], p2[1] - p1[1]), 1e-9)
            e3 = max(math.hypot(p3[0] - p2[0], p3[1] - p2[1]), 1e-9)
            d1, d2, d3 = math.sqrt(e1), math.sqrt(e2), math.sqrt(e3)
            a = 3 * d1 * (d1 + d2)
            b = 3 * d3 * (d3 + d2)
            c1 = tuple((e1 * p2[k] - e2 * p0[k] + (2 * e1 + 3 * d1 * d2 + e2) * p1[k]) / a for k in (0, 1))
            c2 = tuple((e3 * p1[k] - e2 * p3[k] + (2 * e3 + 3 * d3 * d2 + e2) * p2[k]) / b for k in (0, 1))
        else:
            k6 = 1 / 6.0
            c1 = (p1[0] + (p2[0] - p0[0]) * k6, p1[1] + (p2[1] - p0[1]) * k6)
            c2 = (p2[0] - (p3[0] - p1[0]) * k6, p2[1] - (p3[1] - p1[1]) * k6)
        c1 = (p1[0] + (c1[0] - p1[0]) * tension, p1[1] + (c1[1] - p1[1]) * tension)
        c2 = (p2[0] + (c2[0] - p2[0]) * tension, p2[1] + (c2[1] - p2[1]) * tension)
        segs.append((tuple(p1), c1, c2, tuple(p2)))
    return segs


def _bezier_point(seg, t):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = seg
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3)


def sample_polyline(points, tension=1.0, interpolation='catmull-rom'):
    """Ломаная по сплайну: SAMPLES_PER_SEGMENT точек на каждый отрезок, без повтора первой точки."""
    out = []
    for seg in bezier_segments(points, tension, interpolation):
        for j in range(SAMPLES_PER_SEGMENT):
            out.append(_bezier_point(seg, j / SAMPLES_PER_SEGMENT))
    return out


class Polyline:
    """Замкнутая ломаная с длиной дуги: точка по доле длины, отрезок между долями, проекция точки."""

    def __init__(self, pts):
        self.pts = pts
        n = len(pts)
        self.cum = [0.0]
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.length = self.cum[-1] or 1.0

    def _locate(self, frac):
        s = (frac % 1.0) * self.length
        lo, hi = 0, len(self.pts)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        seg_len = self.cum[lo + 1] - self.cum[lo]
        f = (s - self.cum[lo]) / seg_len if seg_len else 0.0
        return lo, f

    def point_at(self, frac):
        i, f = self._locate(frac)
        a, b = self.pts[i], self.pts[(i + 1) % len(self.pts)]
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)

    def tangent_at(self, frac):
        i, _ = self._locate(frac)
        a, b = self.pts[i], self.pts[(i + 1) % len(self.pts)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy) or 1.0
        return (dx / d, dy / d)

    def between(self, fa, fb):
        """Точки от доли fa до fb по направлению движения (с переходом через 0)."""
        span = (fb - fa) % 1.0 or 1.0
        start_s = (fa % 1.0) * self.length
        inner = []
        for i in range(len(self.pts)):
            rel = ((self.cum[i] - start_s) % self.length) / self.length
            if 0 < rel < span:
                inner.append((rel, self.pts[i]))
        inner.sort(key=lambda x: x[0])
        return [self.point_at(fa)] + [p for _, p in inner] + [self.point_at(fa + span)]

    def nearest(self, x, y):
        """(доля длины ближайшей точки линии, расстояние до неё)."""
        best, best_d = 0.0, None
        n = len(self.pts)
        for i in range(n):
            a, b = self.pts[i], self.pts[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            l2 = dx * dx + dy * dy
            t = 0.0 if not l2 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / l2))
            px, py = a[0] + dx * t, a[1] + dy * t
            d = (px - x) ** 2 + (py - y) ** 2
            if best_d is None or d < best_d:
                best_d = d
                best = (self.cum[i] + math.sqrt(l2) * t) / self.length
        return best % 1.0, math.sqrt(best_d or 0.0)

    def project(self, x, y):
        """Доля длины ближайшей к (x, y) точки ломаной."""
        return self.nearest(x, y)[0]

    def contains(self, x, y):
        inside = False
        n = len(self.pts)
        for i in range(n):
            (x1, y1), (x2, y2) = self.pts[i], self.pts[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
        return inside

    def outward_normal(self, frac):
        tx, ty = self.tangent_at(frac)
        nx, ny = ty, -tx
        px, py = self.point_at(frac)
        if self.contains(px + nx * 6, py + ny * 6):
            nx, ny = -nx, -ny
        return (nx, ny)


def polyline(data):
    return Polyline(sample_polyline(data['points'], data.get('tension', 1.0),
                                    data.get('interpolation', 'catmull-rom')))


def view_size(data):
    vb = (data or {}).get('viewBox') or [0, 0, VIEW_W, LEGACY_VIEW_H]
    return vb[2], vb[3]


def signed_area(points):
    """Площадь по формуле шнурка в координатах схемы (ось Y вниз): > 0 — по часовой на экране."""
    n = len(points)
    return sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n)) / 2


def drawn_direction(points):
    return 'cw' if signed_area(points) > 0 else 'ccw'


def sector_bounds(data):
    """Доли начала секторов S1, S2, S3 (от первой опорной точки)."""
    return (data['start'], data['s1s2'], data['s2s3'])


def sector_of(data, frac):
    start, b1, b2 = sector_bounds(data)
    rel = (frac - start) % 1.0
    return 0 if rel < (b1 - start) % 1.0 else (1 if rel < (b2 - start) % 1.0 else 2)


def turn_positions(data, poly=None):
    """[(доля от старта, номер, сектор)] по ходу движения — по ближайшей точке линии к маркеру."""
    poly = poly or polyline(data)
    out = []
    for t in data.get('turns') or []:
        frac = poly.project(t['x'], t['y'])
        out.append(((frac - data['start']) % 1.0, str(t['n']), sector_of(data, frac)))
    out.sort(key=lambda x: x[0])
    return out


def turn_sectors(data, poly=None):
    """{номер поворота: индекс сектора 0..2}."""
    return {n: s for _, n, s in turn_positions(data, poly)}


def sector_turn_ranges(data):
    """['Повороты 1–3', 'Поворот 4', ''] — подписи секторов на странице и в PDF (по ходу движения)."""
    if not data:
        return ['', '', '']
    by_sector = [[], [], []]
    for _, n, s in turn_positions(data):
        by_sector[s].append(n)
    out = []
    for nums in by_sector:
        if not nums:
            out.append('')
        elif len(nums) == 1:
            out.append(f'Поворот {nums[0]}')
        else:
            out.append(f'Повороты {nums[0]}–{nums[-1]}')
    return out


def scale_m_per_unit(data, length_m=None):
    """Метров в единице схемы: из данных (импорт OSM) или по длине трассы из карточки."""
    if data.get('scale_m_per_unit'):
        return float(data['scale_m_per_unit'])
    if length_m:
        return float(length_m) / polyline(data).length
    return None


def stroke_widths(data, length_m=None):
    """(полотно, цветная линия сектора) в единицах схемы: ширина полотна в масштабе, сектор — 45 %, не тоньше 4.5."""
    scale = scale_m_per_unit(data, length_m)
    if not scale:
        return FALLBACK_STROKE, 14
    track = max(4.0, min(60.0, float(data.get('track_width_m') or DEFAULT_TRACK_WIDTH_M) / scale))
    return round(track, 2), round(max(4.5, track * 0.45), 2)


def is_draft(data):
    return bool((data or {}).get('provisional'))


def is_publishable(data):
    """Черновик (есть неподтверждённые элементы) уходит на сайт только по галочке «Опубликовать черновик»."""
    return bool(data) and (not is_draft(data) or bool(data.get('publish_draft')))


def is_osm(data):
    return ((data or {}).get('source') or {}).get('type') == 'osm'


# ── Проверка данных из редактора ────────────────────────────────────────

def _num(value, lo, hi, name):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise SchemeError(f'{name}: ожидается число') from None
    if not math.isfinite(v) or not lo <= v <= hi:
        raise SchemeError(f'{name}: значение вне допустимого диапазона')
    return round(v, 2)


def _clean_source(src):
    if not isinstance(src, dict) or src.get('type') not in ('osm', 'manual', 'svg', 'json'):
        return None
    out = {'type': src['type']}
    for key in ('way', 'osm_version'):
        if isinstance(src.get(key), int) and not isinstance(src.get(key), bool):
            out[key] = src[key]
    for key, size in (('name', 200), ('edited', 20)):
        if isinstance(src.get(key), str):
            out[key] = src[key][:size]
    if isinstance(src.get('reversed'), bool):
        out['reversed'] = src['reversed']
    return out


def clean_scheme_data(raw, length_m=None):
    """Проверка и нормализация JSON из редактора (или импорта). Бросает SchemeError с понятным текстом.
    Отметки принимаются долей длины (start) или координатами (start_xy) — тогда привязываются к линии."""
    if not isinstance(raw, dict):
        raise SchemeError('Нет данных схемы')
    vb = raw.get('viewBox') or [0, 0, VIEW_W, LEGACY_VIEW_H]
    if not isinstance(vb, (list, tuple)) or len(vb) != 4:
        raise SchemeError('viewBox: ожидается [0, 0, 640, высота]')
    height = _num(vb[3], VIEW_H_MIN, VIEW_H_MAX, 'Высота поля схемы')
    if float(vb[2]) != VIEW_W or vb[0] or vb[1]:
        raise SchemeError(f'viewBox: ширина поля должна быть {VIEW_W}')
    width = VIEW_W

    pts = raw.get('points')
    if not isinstance(pts, list) or not 3 <= len(pts) <= MAX_POINTS:
        raise SchemeError(f'Нужно от 3 до {MAX_POINTS} опорных точек')
    margin = 200
    points = []
    for p in pts:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise SchemeError('Точка: ожидается пара [x, y]')
        points.append([_num(p[0], -margin, width + margin, 'x'), _num(p[1], -margin, height + margin, 'y')])
    interpolation = raw.get('interpolation') or 'catmull-rom'
    if interpolation not in INTERPOLATIONS:
        raise SchemeError('Неизвестный способ сглаживания линии')
    data = {
        'version': SCHEME_VERSION,
        'viewBox': [0, 0, width, int(height) if float(height).is_integer() else height],
        'interpolation': interpolation,
        'points': points,
        'tension': _num(raw.get('tension', 1), 0, 1, 'Плавность'),
    }
    poly = polyline(data)
    for key, label in (('start', 'Старт/финиш'), ('s1s2', 'Граница S1|S2'), ('s2s3', 'Граница S2|S3')):
        if raw.get(key) is not None:
            data[key] = round(_num(raw[key], 0, 1, label) % 1.0, 5)
        elif isinstance(raw.get(key + '_xy'), (list, tuple)) and len(raw[key + '_xy']) == 2:
            x = _num(raw[key + '_xy'][0], -margin, width + margin, label)
            y = _num(raw[key + '_xy'][1], -margin, height + margin, label)
            frac, dist = poly.nearest(x, y)
            if dist > MARK_TOLERANCE:
                raise SchemeError(f'{label}: точка не лежит на линии (отстоит на {dist:.1f})')
            data[key] = round(frac, 5)
        else:
            raise SchemeError(f'Не отмечено: {label}')
        px, py = poly.point_at(data[key])
        data[key + '_xy'] = [round(px, 1), round(py, 1)]
    l1 = (data['s1s2'] - data['start']) % 1.0
    l2 = (data['s2s3'] - data['start']) % 1.0
    if not 0 < l1 < l2 < 1:
        raise SchemeError('Порядок отметок по направлению движения должен быть: старт → S1|S2 → S2|S3 → старт')

    turns = raw.get('turns') or []
    if not isinstance(turns, list) or len(turns) > MAX_TURNS:
        raise SchemeError(f'Поворотов не больше {MAX_TURNS}')
    data['turns'] = []
    for t in turns:
        if not isinstance(t, dict):
            raise SchemeError('Поворот: неверный формат')
        n = t.get('n')
        if isinstance(n, float) and n.is_integer():
            n = int(n)
        n = str(n).strip() if n is not None and not isinstance(n, bool) else ''
        if not n or len(n) > 4:
            raise SchemeError('Номер поворота: от 1 до 4 символов')
        data['turns'].append({
            'n': n,
            'x': _num(t.get('x'), -margin, width + margin, 'x поворота'),
            'y': _num(t.get('y'), -margin, height + margin, 'y поворота'),
        })
    labels = raw.get('sector_labels') or []
    data['sector_labels'] = []
    if isinstance(labels, list):
        seen = set()
        for lab in labels:
            if isinstance(lab, dict) and lab.get('s') in (0, 1, 2) and lab['s'] not in seen:
                seen.add(lab['s'])
                data['sector_labels'].append({
                    's': lab['s'],
                    'x': _num(lab.get('x'), -margin, width + margin, 'x подписи'),
                    'y': _num(lab.get('y'), -margin, height + margin, 'y подписи'),
                })

    source = _clean_source(raw.get('source'))
    if source:
        data['source'] = source
    data['rotation_deg'] = _num(raw.get('rotation_deg', 0) or 0, -3600, 3600, 'Поворот схемы')
    data['track_width_m'] = _num(raw.get('track_width_m') or DEFAULT_TRACK_WIDTH_M, 2, 40, 'Ширина полотна')
    if raw.get('scale_m_per_unit'):
        data['scale_m_per_unit'] = round(float(_num(raw['scale_m_per_unit'], 0.0001, 1000, 'Масштаб')), 4) or None
    scale = scale_m_per_unit(data, length_m)
    if scale:
        data['scale_m_per_unit'] = round(scale, 5)
        data['measured_length_m'] = round(poly.length * scale, 1)
    data['direction'] = drawn_direction(points)
    prov = raw.get('provisional') or []
    data['provisional'] = [k for k in PROVISIONAL_KEYS if isinstance(prov, list) and k in prov]
    data['publish_draft'] = bool(raw.get('publish_draft')) and bool(data['provisional'])

    ref = raw.get('reference')
    if isinstance(ref, dict):
        # Положение подложки в редакторе — только для редактора, на сайт не уходит
        data['reference'] = {
            'x': _num(ref.get('x', 0), -5000, 5000, 'Подложка x'),
            'y': _num(ref.get('y', 0), -5000, 5000, 'Подложка y'),
            'scale': _num(ref.get('scale', 1), 0.0001, 50, 'Масштаб подложки'),
            'rotate': _num(ref.get('rotate', 0), -360, 360, 'Поворот подложки'),
            'opacity': _num(ref.get('opacity', 0.5), 0, 1, 'Прозрачность подложки'),
        }
    return data


# ── Раскладка подписей ──────────────────────────────────────────────────

def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def layout(data, length_m=None):
    """Геометрия всех элементов схемы: полотно, старт, подпись старта, стрелка, плашки S1–S3."""
    poly = polyline(data)
    width, height = view_size(data)
    track_w, sector_w = stroke_widths(data, length_m)
    start, b1, b2 = sector_bounds(data)
    half = track_w / 2

    sx, sy = poly.point_at(start)
    tx, ty = poly.tangent_at(start)
    nx, ny = poly.outward_normal(start)
    # как в образце (доп. №1): подпись и стрелка — снаружи линии, подпись ближе к линии
    start_text = (sx + nx * (half + 16), sy + ny * (half + 16))

    arrow_f = start + 6 / poly.length
    ax, ay = poly.point_at(arrow_f)
    anx, any_ = poly.outward_normal(arrow_f)
    atx, aty = poly.tangent_at(arrow_f)
    acx, acy = ax + anx * (half + 30), ay + any_ * (half + 30)
    arrow = {'from': (acx - atx * 28, acy - aty * 28), 'to': (acx + atx * 28, acy + aty * 28),
             'n': (anx, any_), 't': (atx, aty), 'center': (acx, acy)}

    turns = [(t['x'], t['y']) for t in data.get('turns') or []]
    custom = {lab['s']: (lab['x'], lab['y']) for lab in data.get('sector_labels') or []}
    labels = {}
    bounds = (start, b1, b2)
    for s in range(3):
        if s in custom:
            labels[s] = custom[s]
            continue
        lo = bounds[s]
        span = (bounds[(s + 1) % 3] - lo) % 1.0 or 1.0
        # у начала своего сектора; подпись старта и стрелку обходит проверка ниже
        first = 0.04
        best = None
        for step in range(40):
            rel = first + step * 0.025
            if rel > 0.85:
                break
            f = lo + rel * span
            px, py = poly.point_at(f)
            onx, ony = poly.outward_normal(f)
            for side in (1, -1):
                cand = (px + onx * side * (half + 16), py + ony * side * (half + 16))
                if best is None:
                    best = cand
                near_f, near_d = poly.nearest(*cand)
                ok = (
                    sector_of(data, near_f) == s and near_d >= half + 10
                    and 20 <= cand[0] <= width - 20 and 14 <= cand[1] <= height - 14
                    and all(_dist(cand, t) > 26 for t in turns)
                    and _dist(cand, (sx, sy)) > half + 26 and _dist(cand, start_text) > 44
                    and _dist(cand, arrow['center']) > 40
                    and all(_dist(cand, other) > 40 for other in labels.values())
                )
                if ok:
                    best = cand
                    break
            else:
                continue
            break
        labels[s] = best
    return {
        'poly': poly, 'width': width, 'height': height, 'track_w': track_w, 'sector_w': sector_w,
        'start': (sx, sy), 'start_angle': math.degrees(math.atan2(ty, tx)), 'start_text': start_text,
        'arrow': arrow, 'labels': labels,
    }


def label_positions(data, length_m=None):
    """Плашки S1–S3 для редактора: [{s, x, y}] (ручные — как есть, остальные — автоматически)."""
    lay = layout(data, length_m)
    return [{'s': s, 'x': round(lay['labels'][s][0], 1), 'y': round(lay['labels'][s][1], 1)} for s in range(3)]


# ── SVG ─────────────────────────────────────────────────────────────────

def _f(v):
    return f'{v:.1f}'.rstrip('0').rstrip('.') if abs(v) >= 0.05 else '0'


def _path(pts, closed=False):
    d = 'M' + ' L'.join(f'{_f(x)},{_f(y)}' for x, y in pts)
    return d + (' Z' if closed else '')


def render_svg(data, palette='screen', aria_label='', length_m=None):
    """SVG схемы. Подложка-прямоугольник сюда не входит — её рисует шаблон (экран) / лист (PDF)."""
    pal = PALETTES[palette]
    lay = layout(data, length_m)
    poly = lay['poly']
    start, b1, b2 = sector_bounds(data)
    track_w, sector_w = lay['track_w'], lay['sector_w']
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_f(lay["width"])} {_f(lay["height"])}"'
             f' role="img" aria-label="{_esc(aria_label)}">']

    full = _path(poly.pts, closed=True)
    parts.append('<g id="track">')
    parts.append(f'<path d="{full}" fill="none" stroke="{pal["track"]}" stroke-width="{_f(track_w)}"'
                 ' stroke-linejoin="round" stroke-linecap="round"/>')
    if pal['track_inner']:
        parts.append(f'<path d="{full}" fill="none" stroke="{pal["track_inner"]}"'
                     f' stroke-width="{_f(max(track_w - 3, track_w * 0.8))}" stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append('</g>')

    parts.append('<g id="sectors">')
    for s, (fa, fb) in enumerate(((start, b1), (b1, b2), (b2, start))):
        parts.append(f'<path class="sec" data-s="{s}" d="{_path(poly.between(fa, fb))}" fill="none"'
                     f' stroke="{pal["sectors"][s]}" stroke-width="{_f(sector_w)}"'
                     ' stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append('</g>')

    # Старт/финиш: клетчатая полоса поперёк полотна (4 × 2 клетки)
    sx, sy = lay['start']
    h = max(track_w, 10) + 2
    cell = h / 4
    parts.append(f'<g id="start" transform="translate({_f(sx)},{_f(sy)}) rotate({_f(lay["start_angle"])})">')
    stroke = f' stroke="{pal["checker_stroke"]}" stroke-width="0.6"' if pal['checker_stroke'] else ''
    parts.append(f'<rect x="{_f(-cell)}" y="{_f(-h / 2)}" width="{_f(cell * 2)}" height="{_f(h)}" fill="#ffffff"{stroke}/>')
    for row in range(4):
        for col in range(2):
            if (row + col) % 2 == 0:
                parts.append(f'<rect x="{_f(-cell + col * cell)}" y="{_f(-h / 2 + row * cell)}" width="{_f(cell)}"'
                             f' height="{_f(cell)}" fill="{pal["checker_dark"]}"/>')
    parts.append('</g>')
    lx, ly = lay['start_text']
    parts.append(f'<text x="{_f(lx)}" y="{_f(ly + 4)}" text-anchor="middle" fill="{pal["label_text"]}"'
                 ' font-size="10" font-weight="700" letter-spacing="1">СТАРТ / ФИНИШ</text>')

    ar = lay['arrow']
    (x1, y1), (x2, y2), (anx, any_), (atx, aty) = ar['from'], ar['to'], ar['n'], ar['t']
    hx1, hy1 = x2 - atx * 9 + anx * 6, y2 - aty * 9 + any_ * 6
    hx2, hy2 = x2 - atx * 9 - anx * 6, y2 - aty * 9 - any_ * 6
    parts.append(f'<g id="arrow" fill="none" stroke="{pal["arrow"]}" stroke-width="2" stroke-linecap="round"'
                 ' stroke-linejoin="round">')
    parts.append(f'<path d="M{_f(x1)},{_f(y1)} L{_f(x2)},{_f(y2)}"/>')
    parts.append(f'<path d="M{_f(hx1)},{_f(hy1)} L{_f(x2)},{_f(y2)} L{_f(hx2)},{_f(hy2)}"/>')
    parts.append('</g>')

    parts.append('<g id="turns" font-family="JetBrains Mono, SFMono-Regular, Menlo, Consolas, monospace"'
                 ' font-size="10" font-weight="700" text-anchor="middle">')
    for t in data.get('turns') or []:
        n = str(t['n'])
        r = 10 if len(n) <= 2 else 12
        parts.append(f'<circle cx="{_f(t["x"])}" cy="{_f(t["y"])}" r="{r}" fill="{pal["turn_fill"]}"'
                     f' stroke="{pal["turn_stroke"]}" stroke-width="1.5"/>'
                     f'<text x="{_f(t["x"])}" y="{_f(t["y"] + 3.5)}" fill="{pal["turn_text"]}">{_esc(n)}</text>')
    parts.append('</g>')

    parts.append('<g id="labels" font-size="11" font-weight="800" text-anchor="middle">')
    for s in range(3):
        x, y = lay['labels'][s]
        text = SECTOR_TEXT[s] if palette == 'screen' else '#ffffff'
        parts.append(f'<rect class="sec-label" data-s="{s}" x="{_f(x - 16)}" y="{_f(y - 9)}"'
                     f' width="32" height="18" rx="9" fill="{pal["sectors"][s]}"/>'
                     f'<text x="{_f(x)}" y="{_f(y + 4)}" fill="{text}">S{s + 1}</text>')
    parts.append('</g>')
    parts.append('</svg>')
    return ''.join(parts)


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'))


def aria_label(track, data):
    turns = len(data.get('turns') or [])
    bits = ['Схема трассы: три сектора']
    if turns:
        bits.append(f'{turns} поворот' + ('' if turns % 10 == 1 and turns % 100 != 11 else
                                          'а' if 2 <= turns % 10 <= 4 and not 12 <= turns % 100 <= 14 else 'ов'))
    if track.app_direction:
        bits.append('движение ' + ('по часовой стрелке' if track.app_direction == 'cw' else 'против часовой стрелки'))
    return ', '.join(bits)


def public_scheme(data):
    """То, что нужно браузеру для 3D: линия, отметки, поле и ширина полотна (без подписей и подложки)."""
    if not data:
        return None
    out = {k: data[k] for k in ('points', 'tension', 'start', 's1s2', 's2s3', 'turns')}
    out['interpolation'] = data.get('interpolation', 'catmull-rom')
    out['viewBox'] = data.get('viewBox') or [0, 0, VIEW_W, LEGACY_VIEW_H]
    out['track_width_m'] = data.get('track_width_m') or DEFAULT_TRACK_WIDTH_M
    return out


# ── Границы секторов по времени (та же модель скорости, что у 3D-метки) ──

def _curvature(data, length_m, n):
    """Сглаженная кривизна по n точкам круга от старта (как в track_3d.js)."""
    poly = polyline(data)
    mm = float(length_m) / poly.length
    ds = float(length_m) / n
    start = data['start']
    pts = [poly.point_at(start + i / n) for i in range(n)]
    pts = [((x * mm), (y * mm)) for x, y in pts]
    for _ in range(3):
        pts = [(sum(pts[(i + k) % n][0] for k in range(-3, 4)) / 7, sum(pts[(i + k) % n][1] for k in range(-3, 4)) / 7)
               for i in range(n)]
    tang = []
    for i in range(n):
        a, b = pts[(i - 1) % n], pts[(i + 1) % n]
        tx, tz = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(tx, tz) or 1.0
        tang.append((tx / ln, tz / ln))
    curv = []
    for i in range(n):
        u, v = tang[(i - 2) % n], tang[(i + 2) % n]
        curv.append(math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))) / (4 * ds))
    return [sum(curv[(i + k) % n] for k in range(-6, 7)) / 13 for i in range(n)], ds


def _speeds(curv_s, ds, vmax, grip):
    n = len(curv_s)
    vb = [min(vmax, math.sqrt(grip / max(c, 1e-4))) for c in curv_s]
    for _ in range(2):
        for i in range(n):
            pv = vb[(i - 1) % n]
            vb[i] = min(vb[i], math.sqrt(pv * pv + 2 * 3.5 * ds))
    for _ in range(2):
        for i in range(n - 1, -1, -1):
            nv = vb[(i + 1) % n]
            vb[i] = min(vb[i], math.sqrt(nv * nv + 2 * 8 * ds))
    return vb


def speed_profile(data, length_m, n=800, top_kmh=110, lap_sec=None):
    """Накопленное расчётное время по n точкам круга от старта — модель track_3d.js: на прямой не выше top_kmh,
    в повороте √(сцепление/кривизна), разгон 3.5 м/с², торможение 8 м/с²; сцепление подбирается под lap_sec."""
    curv_s, ds = _curvature(data, length_m, n)
    vmax = top_kmh / 3.6

    def lap(grip):
        return sum(ds / v for v in _speeds(curv_s, ds, vmax, grip))

    grip = 18.0
    if lap_sec:
        lo, hi = 3.0, 80.0
        if lap(hi) > lap_sec:
            grip = hi
        else:
            for _ in range(30):
                mid = (lo + hi) / 2
                if lap(mid) > lap_sec:
                    lo = mid
                else:
                    hi = mid
            grip = (lo + hi) / 2
    cum = [0.0]
    for v in _speeds(curv_s, ds, vmax, grip):
        cum.append(cum[-1] + ds / v)
    return cum


def bounds_by_sector_times(data, length_m, shares, top_kmh=110, lap_sec=None):
    """Доли s1s2, s2s3, при которых расчётное время секторов делится как shares (доли S1, S2, S3 во времени круга)."""
    cum = speed_profile(data, length_m, top_kmh=top_kmh, lap_sec=lap_sec)
    n = len(cum) - 1
    total = cum[-1]

    def frac_at(t):
        lo, hi = 0, n
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if cum[mid] <= t:
                lo = mid
            else:
                hi = mid
        f = (t - cum[lo]) / ((cum[lo + 1] - cum[lo]) or 1)
        return (lo + f) / n

    s = sum(shares)
    b1 = frac_at(total * shares[0] / s)
    b2 = frac_at(total * (shares[0] + shares[1]) / s)
    start = data['start']
    return round((start + b1) % 1.0, 5), round((start + b2) % 1.0, 5)
