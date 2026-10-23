"""Схема трассы: геометрия осевой линии и SVG для страницы трассы и PDF.

Источник — Track.scheme_data, его пишет редактор схемы в админке
(website/track_scheme_admin.py). SVG строится здесь, на сервере, из
проверенных чисел — в Track.scheme_svg никогда не попадает разметка из
браузера, так что схема не может принести на сайт скрипт.

Линия — замкнутый сплайн Catmull-Rom через опорные точки (по направлению
движения), каждый отрезок — кубическая кривая Безье. Для деления на
секторы кривая дискретизируется в ломаную (SAMPLES_PER_SEGMENT точек на
отрезок), отметки «старт» / «S1|S2» / «S2|S3» — доли длины этой ломаной
от первой опорной точки. Та же дискретизация повторена в
website/static/website/js/track_scheme_geom.js (редактор и 3D) — при
правке менять оба места, тест website/tests/test_track_scheme.py сверяет их.
"""
import math

VIEW_W, VIEW_H = 640, 400
SAMPLES_PER_SEGMENT = 20
SCHEME_VERSION = 1

MAX_POINTS = 400

# Расстояния вдоль линии (единицы схемы) от старта/границы до стрелки и плашек
ARROW_AT = 50
LABEL_AFTER_START = 110
LABEL_AFTER_BOUND = 25
MAX_TURNS = 60

# Цвета секторов: экран (тёмная тема сайта) и печать (тёмные варианты — светлый лист, ч/б)
SECTOR_COLORS = ('#ffc107', '#0dcaf0', '#28a745')
SECTOR_TEXT = ('#1a1a25', '#1a1a25', '#ffffff')
PRINT_SECTOR_COLORS = ('#e0a800', '#0a8fb0', '#1e7e34')

PALETTES = {
    'screen': {
        'track': '#2a2a35', 'track_inner': None, 'sectors': SECTOR_COLORS, 'sector_width': 14,
        'turn_fill': '#15151c', 'turn_stroke': '#eceff1', 'turn_text': '#ffffff',
        'label_text': '#adb5bd', 'arrow': '#ffffff', 'checker_dark': '#0d0d15', 'checker_stroke': None,
    },
    'print': {
        'track': '#1a1a25', 'track_inner': '#e4e4e8', 'sectors': PRINT_SECTOR_COLORS, 'sector_width': 9,
        'turn_fill': '#ffffff', 'turn_stroke': '#1a1a25', 'turn_text': '#1a1a25',
        'label_text': '#1a1a25', 'arrow': '#1a1a25', 'checker_dark': '#1a1a25', 'checker_stroke': '#1a1a25',
    },
}


class SchemeError(ValueError):
    """Данные схемы из редактора не прошли проверку."""


# ── Геометрия ────────────────────────────────────────────────────────────

def bezier_segments(points, tension=1.0):
    """Замкнутый Catmull-Rom → список кубических Безье (p0, c1, c2, p1).
    tension — «Плавность» редактора: 0 — ломаная, 1 — классический Catmull-Rom."""
    n = len(points)
    k = tension / 6.0
    segs = []
    for i in range(n):
        p0, p1 = points[i - 1], points[i]
        p2, p3 = points[(i + 1) % n], points[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) * k, p1[1] + (p2[1] - p0[1]) * k)
        c2 = (p2[0] - (p3[0] - p1[0]) * k, p2[1] - (p3[1] - p1[1]) * k)
        segs.append((tuple(p1), c1, c2, tuple(p2)))
    return segs


def _bezier_point(seg, t):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = seg
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3)


def sample_polyline(points, tension=1.0):
    """Ломаная по сплайну: SAMPLES_PER_SEGMENT точек на каждый отрезок, без повтора первой точки."""
    out = []
    for seg in bezier_segments(points, tension):
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

    def project(self, x, y):
        """Доля длины ближайшей к (x, y) точки ломаной."""
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
        return best % 1.0

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


def signed_area(points):
    """Площадь по формуле шнурка в координатах схемы (ось Y вниз): > 0 — по часовой на экране."""
    n = len(points)
    return sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n)) / 2


def drawn_direction(points):
    return 'cw' if signed_area(points) > 0 else 'ccw'


def sector_bounds(data):
    """Доли начала секторов S1, S2, S3 (от первой опорной точки)."""
    return (data['start'], data['s1s2'], data['s2s3'])


def turn_sectors(data, poly=None):
    """{номер поворота: индекс сектора 0..2} — по проекции маркера на линию."""
    poly = poly or Polyline(sample_polyline(data['points'], data.get('tension', 1.0)))
    start, b1, b2 = sector_bounds(data)
    l1, l2 = (b1 - start) % 1.0, (b2 - start) % 1.0
    out = {}
    for t in data.get('turns') or []:
        rel = (poly.project(t['x'], t['y']) - start) % 1.0
        out[t['n']] = 0 if rel < l1 else (1 if rel < l2 else 2)
    return out


def sector_turn_ranges(data):
    """['Повороты 1–3', 'Поворот 4', ''] — подписи секторов на странице и в PDF."""
    if not data:
        return ['', '', '']
    by_sector = [[], [], []]
    for n, s in turn_sectors(data).items():
        by_sector[s].append(n)
    out = []
    for nums in by_sector:
        nums.sort()
        if not nums:
            out.append('')
        elif len(nums) == 1:
            out.append(f'Поворот {nums[0]}')
        else:
            out.append(f'Повороты {nums[0]}–{nums[-1]}')
    return out


# ── Проверка данных из редактора ────────────────────────────────────────

def _num(value, lo, hi, name):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise SchemeError(f'{name}: ожидается число') from None
    if not math.isfinite(v) or not lo <= v <= hi:
        raise SchemeError(f'{name}: значение вне допустимого диапазона')
    return round(v, 2)


def clean_scheme_data(raw):
    """Проверка и нормализация JSON из редактора. Бросает SchemeError с понятным текстом."""
    if not isinstance(raw, dict):
        raise SchemeError('Нет данных схемы')
    pts = raw.get('points')
    if not isinstance(pts, list) or not 3 <= len(pts) <= MAX_POINTS:
        raise SchemeError(f'Нужно от 3 до {MAX_POINTS} опорных точек')
    margin = 200
    points = []
    for p in pts:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise SchemeError('Точка: ожидается пара [x, y]')
        points.append([_num(p[0], -margin, VIEW_W + margin, 'x'), _num(p[1], -margin, VIEW_H + margin, 'y')])
    data = {
        'version': SCHEME_VERSION,
        'viewBox': [0, 0, VIEW_W, VIEW_H],
        'points': points,
        'tension': _num(raw.get('tension', 1), 0, 1, 'Плавность'),
    }
    for key, label in (('start', 'Старт/финиш'), ('s1s2', 'Граница S1|S2'), ('s2s3', 'Граница S2|S3')):
        if raw.get(key) is None:
            raise SchemeError(f'Не отмечено: {label}')
        data[key] = round(_num(raw[key], 0, 1, label) % 1.0, 5)
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
        data['turns'].append({
            'n': int(_num(t.get('n'), 1, 99, 'Номер поворота')),
            'x': _num(t.get('x'), -margin, VIEW_W + margin, 'x поворота'),
            'y': _num(t.get('y'), -margin, VIEW_H + margin, 'y поворота'),
        })
    labels = raw.get('sector_labels') or []
    data['sector_labels'] = []
    if isinstance(labels, list):
        for lab in labels[:3]:
            if isinstance(lab, dict) and lab.get('s') in (0, 1, 2):
                data['sector_labels'].append({
                    's': lab['s'],
                    'x': _num(lab.get('x'), -margin, VIEW_W + margin, 'x подписи'),
                    'y': _num(lab.get('y'), -margin, VIEW_H + margin, 'y подписи'),
                })
    ref = raw.get('reference')
    if isinstance(ref, dict):
        # Положение подложки в редакторе — только для редактора, на сайт не уходит
        data['reference'] = {
            'x': _num(ref.get('x', 0), -5000, 5000, 'Подложка x'),
            'y': _num(ref.get('y', 0), -5000, 5000, 'Подложка y'),
            'scale': _num(ref.get('scale', 1), 0.01, 50, 'Масштаб подложки'),
            'rotate': _num(ref.get('rotate', 0), -360, 360, 'Поворот подложки'),
            'opacity': _num(ref.get('opacity', 0.5), 0, 1, 'Прозрачность подложки'),
        }
    return data


# ── SVG ─────────────────────────────────────────────────────────────────

def _f(v):
    return f'{v:.1f}'.rstrip('0').rstrip('.') if abs(v) >= 0.05 else '0'


def _path(pts, closed=False):
    d = 'M' + ' L'.join(f'{_f(x)},{_f(y)}' for x, y in pts)
    return d + (' Z' if closed else '')


def default_label_positions(data, poly):
    """Плашки S1/S2/S3 — у начала сектора с внешней стороны линии."""
    out = []
    for s, frac in enumerate(sector_bounds(data)):
        # S1 — дальше стрелки направления, остальные — сразу за границей
        f = frac + (LABEL_AFTER_START if s == 0 else LABEL_AFTER_BOUND) / poly.length
        x, y = poly.point_at(f)
        nx, ny = poly.outward_normal(f)
        out.append({'s': s, 'x': round(x + nx * 30, 1), 'y': round(y + ny * 30, 1)})
    return out


def render_svg(data, palette='screen', aria_label=''):
    """SVG схемы. Подложка-прямоугольник сюда не входит — её рисует шаблон (экран) / лист (PDF)."""
    pal = PALETTES[palette]
    poly = Polyline(sample_polyline(data['points'], data.get('tension', 1.0)))
    start, b1, b2 = sector_bounds(data)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" role="img"'
             f' aria-label="{_esc(aria_label)}">']

    full = _path(poly.pts, closed=True)
    parts.append('<g id="track">')
    parts.append(f'<path d="{full}" fill="none" stroke="{pal["track"]}" stroke-width="30"'
                 ' stroke-linejoin="round" stroke-linecap="round"/>')
    if pal['track_inner']:
        parts.append(f'<path d="{full}" fill="none" stroke="{pal["track_inner"]}" stroke-width="26"'
                     ' stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append('</g>')

    parts.append('<g id="sectors">')
    for s, (fa, fb) in enumerate(((start, b1), (b1, b2), (b2, start))):
        parts.append(f'<path class="sec" data-s="{s}" d="{_path(poly.between(fa, fb))}" fill="none"'
                     f' stroke="{pal["sectors"][s]}" stroke-width="{pal["sector_width"]}"'
                     ' stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append('</g>')

    # Старт/финиш: клетчатая полоса поперёк линии
    sx, sy = poly.point_at(start)
    tx, ty = poly.tangent_at(start)
    angle = math.degrees(math.atan2(ty, tx))
    parts.append(f'<g id="start" transform="translate({_f(sx)},{_f(sy)}) rotate({_f(angle)})">')
    stroke = f' stroke="{pal["checker_stroke"]}" stroke-width="0.8"' if pal['checker_stroke'] else ''
    parts.append(f'<rect x="-4" y="-15" width="8" height="30" fill="#ffffff"{stroke}/>')
    for row in range(4):
        for col in range(2):
            if (row + col) % 2 == 0:
                parts.append(f'<rect x="{-4 + col * 4}" y="{-15 + row * 7.5}" width="4" height="7.5"'
                             f' fill="{pal["checker_dark"]}"/>')
    parts.append('</g>')
    # подпись — с внутренней стороны линии, стрелка и плашка S1 — с внешней (как в макете)
    nx, ny = poly.outward_normal(start)
    lx, ly = sx - nx * 30, sy - ny * 30
    parts.append(f'<text x="{_f(lx)}" y="{_f(ly + 4)}" text-anchor="middle" fill="{pal["label_text"]}"'
                 ' font-size="11" font-weight="700" letter-spacing="1">СТАРТ / ФИНИШ</text>')

    # Стрелка направления — чуть дальше старта, с внешней стороны
    af = start + ARROW_AT / poly.length
    ax, ay = poly.point_at(af)
    anx, any_ = poly.outward_normal(af)
    atx, aty = poly.tangent_at(af)
    cx, cy = ax + anx * 26, ay + any_ * 26
    x1, y1 = cx - atx * 30, cy - aty * 30
    x2, y2 = cx + atx * 30, cy + aty * 30
    hx1, hy1 = x2 - atx * 9 + anx * 6, y2 - aty * 9 + any_ * 6
    hx2, hy2 = x2 - atx * 9 - anx * 6, y2 - aty * 9 - any_ * 6
    parts.append(f'<g id="arrow" fill="none" stroke="{pal["arrow"]}" stroke-width="2" stroke-linecap="round"'
                 ' stroke-linejoin="round">')
    parts.append(f'<path d="M{_f(x1)},{_f(y1)} L{_f(x2)},{_f(y2)}"/>')
    parts.append(f'<path d="M{_f(hx1)},{_f(hy1)} L{_f(x2)},{_f(y2)} L{_f(hx2)},{_f(hy2)}"/>')
    parts.append('</g>')

    parts.append('<g id="turns" font-family="JetBrains Mono, SFMono-Regular, Menlo, Consolas, monospace"'
                 ' font-size="11" font-weight="700" text-anchor="middle">')
    for t in data.get('turns') or []:
        parts.append(f'<circle cx="{_f(t["x"])}" cy="{_f(t["y"])}" r="11" fill="{pal["turn_fill"]}"'
                     f' stroke="{pal["turn_stroke"]}" stroke-width="1.5"/>'
                     f'<text x="{_f(t["x"])}" y="{_f(t["y"] + 4)}" fill="{pal["turn_text"]}">{int(t["n"])}</text>')
    parts.append('</g>')

    labels = {lab['s']: lab for lab in default_label_positions(data, poly)}
    for lab in data.get('sector_labels') or []:
        labels[lab['s']] = lab
    parts.append('<g id="labels" font-size="12" font-weight="800" text-anchor="middle">')
    for s in range(3):
        lab = labels[s]
        fill = pal['sectors'][s]
        text = SECTOR_TEXT[s] if palette == 'screen' else '#ffffff'
        parts.append(f'<rect class="sec-label" data-s="{s}" x="{_f(lab["x"] - 17)}" y="{_f(lab["y"] - 10)}"'
                     f' width="34" height="20" rx="10" fill="{fill}"/>'
                     f'<text x="{_f(lab["x"])}" y="{_f(lab["y"] + 4)}" fill="{text}">S{s + 1}</text>')
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
    """То, что нужно браузеру для 3D: опорные точки и отметки (без подписей, без подложки)."""
    if not data:
        return None
    return {k: data[k] for k in ('points', 'tension', 'start', 's1s2', 's2s3', 'turns')}
