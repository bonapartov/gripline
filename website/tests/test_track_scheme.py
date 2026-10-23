"""Схема трассы: проверка данных редактора, SVG, подписи секторов, паритет Python ↔ JS."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from website.services import track_scheme as ts

GEOM_JS = Path(__file__).resolve().parents[1] / 'static' / 'website' / 'js' / 'track_scheme_geom.js'


def oval(n=24, cx=320, cy=200, rx=220, ry=120, clockwise=False):
    """Эллипс в координатах схемы. С осью Y вниз рост угла — по часовой на экране."""
    pts = [[round(cx + rx * math.cos(2 * math.pi * i / n), 2), round(cy + ry * math.sin(2 * math.pi * i / n), 2)]
           for i in range(n)]
    return pts if clockwise else pts[::-1]


def scheme(**kw):
    data = {'points': oval(), 'tension': 1, 'start': 0.0, 's1s2': 0.3, 's2s3': 0.65,
            'turns': [{'n': 1, 'x': 540, 'y': 200}, {'n': 2, 'x': 320, 'y': 70}, {'n': 3, 'x': 100, 'y': 200}]}
    data.update(kw)
    return ts.clean_scheme_data(data)


def test_clean_accepts_valid_and_drops_unknown_keys():
    raw = {'points': oval(), 'start': 0.1, 's1s2': 0.4, 's2s3': 0.7, 'evil': '<script>', 'turns': []}
    data = ts.clean_scheme_data(raw)
    assert 'evil' not in data
    assert data['version'] == ts.SCHEME_VERSION and data['viewBox'] == [0, 0, 640, 400]


@pytest.mark.parametrize('bad, message', [
    ({'points': [[0, 0], [1, 1]]}, 'опорных точек'),
    ({'points': oval(), 's1s2': 0.3, 's2s3': 0.6}, 'Старт'),
    ({'points': oval(), 'start': 0, 's1s2': 0.6, 's2s3': 0.3}, 'Порядок'),
    ({'points': [[0, 0], ['x', 1], [5, 5]], 'start': 0, 's1s2': 0.3, 's2s3': 0.6}, 'число'),
    ({'points': oval(), 'start': 0, 's1s2': 0.3, 's2s3': 0.6, 'turns': [{'n': 1, 'x': 1e9, 'y': 0}]}, 'диапазона'),
])
def test_clean_rejects_bad_data(bad, message):
    with pytest.raises(ts.SchemeError, match=message):
        ts.clean_scheme_data(bad)


def test_marks_wrap_around_start():
    # старт ближе к концу линии: 0.9 → 0.2 → 0.5 — корректный порядок с переходом через 0
    data = ts.clean_scheme_data({'points': oval(), 'start': 0.9, 's1s2': 0.2, 's2s3': 0.5})
    assert data['start'] == 0.9


def test_svg_has_layers_and_no_markup_from_input():
    data = scheme()
    svg = ts.render_svg(data, aria_label='Схема "тест" <b>')
    for layer in ('id="track"', 'id="sectors"', 'id="start"', 'id="arrow"', 'id="turns"', 'id="labels"'):
        assert layer in svg
    assert svg.count('class="sec"') == 3
    assert '<b>' not in svg and '&quot;тест&quot;' in svg


def test_print_palette_uses_dark_sector_colors():
    svg = ts.render_svg(scheme(), palette='print')
    for color in ts.PRINT_SECTOR_COLORS:
        assert color in svg
    assert ts.SECTOR_COLORS[0] not in svg


def test_sector_paths_cover_whole_line():
    data = scheme()
    poly = ts.Polyline(ts.sample_polyline(data['points'], data['tension']))

    def length(pts):
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))

    total = sum(length(poly.between(a, b)) for a, b in ((0.0, 0.3), (0.3, 0.65), (0.65, 0.0)))
    assert total == pytest.approx(poly.length, rel=1e-6)
    assert length(poly.between(0.0, 0.3)) == pytest.approx(poly.length * 0.3, rel=1e-6)


def test_turn_ranges_by_sector():
    data = scheme(turns=[{'n': 1, 'x': 500, 'y': 115}, {'n': 2, 'x': 320, 'y': 70},
                         {'n': 3, 'x': 100, 'y': 190}, {'n': 4, 'x': 320, 'y': 330}])
    by_turn = ts.turn_sectors(data)
    assert set(by_turn) == {1, 2, 3, 4}
    # повороты идут по ходу трассы — номер сектора не убывает
    assert [by_turn[n] for n in (1, 2, 3, 4)] == sorted(by_turn[n] for n in (1, 2, 3, 4))
    ranges = ts.sector_turn_ranges(data)
    assert len(ranges) == 3 and any(r.startswith('Повороты') or r.startswith('Поворот ') for r in ranges)
    assert ts.sector_turn_ranges(scheme(turns=[])) == ['', '', '']


def test_drawn_direction():
    assert ts.drawn_direction(oval(clockwise=True)) == 'cw'
    assert ts.drawn_direction(oval(clockwise=False)) == 'ccw'


def test_public_scheme_hides_editor_only_fields():
    data = scheme(reference={'x': 1, 'y': 2, 'scale': 1, 'rotate': 0, 'opacity': 0.5},
                  sector_labels=[{'s': 0, 'x': 10, 'y': 10}])
    pub = ts.public_scheme(data)
    assert 'reference' not in pub and 'sector_labels' not in pub
    assert set(pub) == {'points', 'tension', 'start', 's1s2', 's2s3', 'turns'}


@pytest.mark.skipif(not shutil.which('node'), reason='нет Node.js')
def test_js_geometry_matches_python():
    """track_scheme_geom.js (редактор, 3D) и track_scheme.py (SVG сайта) дают одну и ту же линию."""
    data = scheme(tension=0.7)
    poly = ts.Polyline(ts.sample_polyline(data['points'], data['tension']))
    fracs = [0, 0.13, 0.5, 0.77, 0.999]
    expected = {
        'length': poly.length,
        'points': [poly.point_at(f) for f in fracs],
        'project': poly.project(500, 120),
        'n': len(poly.pts),
    }
    script = (
        "const G=require(%s);const d=%s;const p=G.fromScheme(d);"
        "console.log(JSON.stringify({length:p.length,points:%s.map(f=>p.pointAt(f)),"
        "project:p.project(500,120).frac,n:p.pts.length}));"
    ) % (json.dumps(str(GEOM_JS)), json.dumps(data), json.dumps(fracs))
    out = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True).stdout)
    assert out['n'] == expected['n']
    assert out['length'] == pytest.approx(expected['length'], rel=1e-9)
    assert out['project'] == pytest.approx(expected['project'], abs=1e-9)
    for a, b in zip(out['points'], expected['points']):
        assert a == pytest.approx(list(b), abs=1e-6)
