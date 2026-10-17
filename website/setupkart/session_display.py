"""Сессия приложения для показа на сайте: разделы и поля с подписями.

Подписи — из копии профиля приложения `app_profile_common.json` (`assets/profiles/common.json` репозитория
приложения; при изменении профиля там — скопировать сюда) и поля карбюратора — `APP_ENGINE_FIELD_CHOICES`.
Значения хранятся снимком `ключ → значение`, составные поля — с точкой (`pressure.fl.cold`, `weight.lf`).
"""
import json
from functools import lru_cache
from pathlib import Path

PROFILE = Path(__file__).with_name('app_profile_common.json')
COMPOSITE = {'pressure4', 'balance4', 'tyre_temps4'}
SKIP = {'photo', 'computed'}
PARTS = {
    'fl': 'ПЛ', 'fr': 'ПП', 'rl': 'ЗЛ', 'rr': 'ЗП', 'lf': 'ПЛ', 'rf': 'ПП', 'lr': 'ЗЛ',
    'cold': 'хол.', 'warm': 'гор.', 'hot': 'гор.', 'in': 'внутри', 'mid': 'середина', 'out': 'снаружи',
}


@lru_cache(maxsize=1)
def profile_sections():
    return json.loads(PROFILE.read_text(encoding='utf-8'))['sections']


def laptime(ms):
    if not isinstance(ms, (int, float)) or ms <= 0:
        return ''
    ms = int(ms)
    m, rest = divmod(ms, 60000)
    return f'{m}:{rest / 1000:06.3f}' if m else f'{rest / 1000:.3f}'


def _option_label(field, value):
    for o in field.get('options') or []:
        if isinstance(o, dict) and str(o.get('value')) == str(value):
            return o.get('label') or str(value)
    return str(value)


def _fmt(field, value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if field.get('type') == 'laptime':
        return laptime(value)
    text = _option_label(field, value) if field.get('options') else str(value)
    unit = field.get('unit') or ''
    return f'{text} {unit}'.strip()


def _composite(field, setup):
    prefix = field['key'] + '.'
    parts = []
    for key in sorted(k for k in setup if k.startswith(prefix)):
        value = setup[key]
        if value in (None, '') or isinstance(value, (dict, list)):
            continue
        name = ' '.join(PARTS.get(p, p) for p in key[len(prefix):].split('.'))
        parts.append(f'{name}: {_fmt(field, value)}')
    return '; '.join(parts)


def laps_summary(setup):
    laps = [x for x in (setup.get('laps') or []) if isinstance(x, (int, float)) and x > 0]
    if not laps:
        return ''
    return f'{len(laps)} кр., лучший {laptime(min(laps))}'


def sections(setup):
    """[(заголовок, [(подпись, значение), …]), …] — только заполненные поля."""
    from website.models import APP_ENGINE_FIELD_CHOICES
    out = []
    for section in profile_sections():
        rows = []
        if section['key'] == 'carburetor_slot':
            for key, label in APP_ENGINE_FIELD_CHOICES:
                if setup.get(key) not in (None, ''):
                    rows.append((label, str(setup[key])))
            if rows:
                out.append(('Карбюратор', rows))
            continue
        for field in section['fields']:
            kind, key = field.get('type'), field['key']
            if kind in SKIP:
                continue
            if kind == 'laps':
                text = laps_summary(setup)
            elif kind in COMPOSITE:
                text = _composite(field, setup)
            else:
                value = setup.get(key)
                text = '' if value in (None, '') or isinstance(value, (dict, list)) else _fmt(field, value)
            if text:
                rows.append((field['label'], text))
        if rows:
            out.append((section['title'] or 'Прочее', rows))
    return out
