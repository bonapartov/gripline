"""Контекст страницы трассы /tracks/<slug>/ (без списков этапов — их собирает track_detail_view)."""
import re
from urllib.parse import quote

from django.conf import settings
from django.templatetags.static import static
from django.utils.safestring import mark_safe

from website.services import track_scheme, track_stats


def _kart_scale():
    """Размер метки-карта в 3D относительно настоящего — общая настройка в админке (Трассы → Настройки страницы)."""
    from website.models import TrackPageSettings
    return float(TrackPageSettings.get().kart_scale)


def map_links(track):
    """Карта и ссылки «Проложить маршрут» / «Яндекс Карты» по координатам трассы."""
    if track.latitude is None or track.longitude is None:
        return None
    lat, lon = track.latitude, track.longitude
    ll = f'{lon},{lat}'
    return {
        'coords': f'{lat:.4f}, {lon:.4f}',
        'lat': lat,
        'lon': lon,
        # JS API Яндекс.Карт, как на /pulse/ — без рекламных блоков iframe-виджета
        'api_url': f'https://api-maps.yandex.ru/2.1/?apikey={settings.YANDEX_MAPS_API_KEY}&lang=ru_RU',
        'route_url': f'https://yandex.ru/maps/?rtext=~{lat},{lon}&rtt=auto',
        'maps_url': f'https://yandex.ru/maps/?pt={quote(ll)}&z=16&l=map',
    }


# Порог средней скорости сектора в 3D (выше — время секторов не сходится со схемой, метка не едет).
# Быстрые классы — KZ/KZ2 (в т.ч. Masters) и DD2 (в т.ч. Masters) — 130 км/ч, остальные 120 (владелец 24.10.2026).
MAX_SECTOR_KMH = 120
MAX_SECTOR_KMH_FAST = 130
FAST_CLASS_RE = re.compile(r'KZ|DD2', re.IGNORECASE)


def max_sector_kmh(class_name):
    return MAX_SECTOR_KMH_FAST if FAST_CLASS_RE.search(class_name or '') else MAX_SECTOR_KMH


# Максимальная скорость карта класса на прямой для 3D-метки (км/ч). Сцепление в поворотах 3D подбирает
# само так, чтобы расчётный круг совпал с рекордом. Без этого у Micro на Лемаре метка разгонялась до 120 км/ч.
# Первое совпадение по названию класса (без учёта регистра), иначе DEFAULT_TOP_KMH.
TOP_SPEED_KMH = (
    (r'micro|микро', 80),
    (r'супер.?мини|super.?mini', 100),
    (r'mini|мини|бамбини|bambini', 95),
    (r'\bkz', 135),
    (r'dd2', 120),
    (r'ok.?j|ок.?j|ок.?юн', 115),
    (r'junior|юниор|юноши', 110),
    (r'senior|сеньор|взрослые', 115),
    (r'\bok\b|\bок\b', 125),
)
DEFAULT_TOP_KMH = 110


def top_speed_kmh(class_name):
    name = class_name or ''
    for pattern, kmh in TOP_SPEED_KMH:
        if re.search(pattern, name, re.IGNORECASE):
            return kmh
    return DEFAULT_TOP_KMH


def _js_class(c):
    """Минимум для JS: переключатель классов, адрес ?class=, 3D-метка."""
    return {
        'id': c['id'],
        'name': c['name'],
        'max_sector_kmh': max_sector_kmh(c['name']),
        'top_kmh': top_speed_kmh(c['name']),
        'record_ms': c['record']['ms'] if c['record'] else None,
        'sectors_ms': [s['ms'] for s in c['sectors']] if c['has_sectors'] else None,
    }


def build_track_page(track, requested_class, races_count):
    rows = track_stats.load_rows(track)
    classes = track_stats.build_track_classes(rows)

    selected = None
    if requested_class and str(requested_class).isdigit():
        selected = next((c for c in classes if c['id'] == int(requested_class)), None)
    selected = selected or track_stats.default_class(classes)

    scheme = track.scheme_data if track.has_scheme else None
    turn_ranges = track_scheme.sector_turn_ranges(scheme) if scheme else ['', '', '']
    # 3D: нужна и схема, и длина (масштаб), и WebGL в браузере (проверяет JS)
    can_3d = bool(scheme and track.length_m)
    for c in classes:
        for sec in c['sectors']:
            sec['turns'] = turn_ranges[sec['index']]

    js_data = {
        'classes': [_js_class(c) for c in classes],
        'selected': selected['id'] if selected else None,
        'scheme': track_scheme.public_scheme(scheme) if can_3d else None,
        'length_m': float(track.length_m) if track.length_m else None,
        'turn_ranges': turn_ranges,
        'kart_scale': _kart_scale(),
        'static': {
            'three': static('website/vendor/three/r128/three.min.js'),
            'orbit': static('website/vendor/three/r128/OrbitControls.js'),
            'geom': static('website/js/track_scheme_geom.js'),
            'kart': static('website/js/track_3d_kart.js'),
            'module': static('website/js/track_3d.js'),
        },
    }

    return {
        'classes': classes,
        'selected_class': selected,
        'absolute_record': track_stats.absolute_record(classes),
        'races_count': races_count,
        'turns_count': track.effective_turns_count,
        'scheme_svg': mark_safe(track.scheme_svg) if scheme else '',  # строится на сервере из чисел
        # лицензия OpenStreetMap (ODbL): мелкая подпись под схемой (доп. №1, Д7)
        'scheme_osm': bool(scheme) and track_scheme.is_osm(scheme),
        'turn_ranges': turn_ranges,
        'can_3d': can_3d,
        'track_js': js_data,
        'map': map_links(track),
        # «Код карты» из админки — только если у трассы нет координат
        'map_html': mark_safe(track.map_html) if track.map_html and track.latitude is None else '',
    }
