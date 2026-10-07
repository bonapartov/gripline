"""Описание значений поля (диапазон или список) → формат профиля приложения и проверка.

Формат совпадает с профилями внутри приложения (`assets/profiles/*.json` в gripline-setupkart):
`{"options": [...]}` или `{"range": {"from", "to", "step", "decimals", "prefix"}}`.
"""
from decimal import Decimal

MAX_OPTIONS = 500

# Параметры, которые в приложении — числовое поле «−/+», а не список (проставки, шаг 0.5).
STEPPER_KEYS = {'spacer'}


def D(x):
    return None if x is None or x == '' else Decimal(str(x))


def is_stepper(spec):
    return getattr(spec, 'key', None) in STEPPER_KEYS and not hasattr(spec, 'engine_id')


def decimals_of(step):
    """0.25 → 2, 0.5 → 1, 1 → 0."""
    if step is None:
        return 0
    exp = Decimal(step).normalize().as_tuple().exponent
    return max(0, -exp)


def expand(spec):
    """Все значения поля строками — так их хранит и показывает приложение."""
    if spec.mode == spec.MODE_LIST:
        return [line.strip() for line in (spec.options_text or '').splitlines() if line.strip()]
    lo, hi, step = D(spec.min_value), D(spec.max_value), D(spec.step)
    if lo is None or hi is None or not step or step <= 0:
        return []
    count = int(((hi - lo) / step).to_integral_value())
    if count + 1 > MAX_OPTIONS:
        return []
    d = decimals_of(step)
    return [f"{spec.prefix}{(lo + step * i):.{d}f}" for i in range(count + 1)]


def spec_errors(spec):
    """{поле формы: сообщение} — пусто, если всё верно."""
    errors = {}
    stepper = is_stepper(spec)
    if stepper and spec.mode != spec.MODE_RANGE:
        return {'mode': 'Это числовое поле «−/+» — задайте минимум, максимум и шаг.'}
    if spec.mode == spec.MODE_RANGE:
        lo, hi, step = D(spec.min_value), D(spec.max_value), D(spec.step)
        if lo is None:
            errors['min_value'] = 'Укажите минимум.'
        if hi is None:
            errors['max_value'] = 'Укажите максимум.'
        if not step or step <= 0:
            errors['step'] = 'Шаг должен быть больше нуля.'
        if lo is not None and hi is not None and lo >= hi:
            errors['max_value'] = 'Максимум должен быть больше минимума.'
        if not errors and not stepper and (hi - lo) / step + 1 > MAX_OPTIONS:
            errors['step'] = f'Слишком много значений (больше {MAX_OPTIONS}) — увеличьте шаг.'
        if not errors and ((hi - lo) % step) != 0:
            errors['max_value'] = 'Максимум не попадает в шаг от минимума.'
        if not errors and stepper and spec.default_value:
            try:
                dv = Decimal(spec.default_value.replace(',', '.'))
            except Exception:
                dv = None
            if dv is None or not (lo <= dv <= hi) or (dv - lo) % step != 0:
                errors['default_value'] = 'Значение по умолчанию вне диапазона или не попадает в шаг.'
            return errors
    else:
        if not expand(spec):
            errors['options_text'] = 'Добавьте хотя бы одно значение.'
    if spec.default_value and not errors and spec.default_value not in expand(spec):
        errors['default_value'] = 'Значения по умолчанию нет среди допустимых.'
    return errors


def to_profile_field(spec, key, label, extra=None):
    """Поле в формате профиля приложения."""
    if is_stepper(spec):
        field = {'key': key, 'label': spec.label or label, 'type': 'number',
                 'min': float(spec.min_value), 'max': float(spec.max_value), 'step': float(spec.step),
                 'decimals': decimals_of(spec.step)}
        if spec.unit:
            field['unit'] = spec.unit
        if spec.default_value:
            field['default'] = float(spec.default_value.replace(',', '.'))
        return field
    field = {
        'key': key,
        'label': spec.label or label,
        'type': 'radio' if key == 'needle_position' else 'choice',
        'allow_custom': spec.allow_custom,
    }
    if spec.unit:
        field['unit'] = spec.unit
    if spec.mode == spec.MODE_RANGE:
        field['range'] = {
            'from': float(spec.min_value), 'to': float(spec.max_value), 'step': float(spec.step),
            'decimals': decimals_of(D(spec.step)), 'prefix': spec.prefix or '',
        }
    else:
        field['options'] = expand(spec)
    if key == 'needle_position':
        labels = {'1': '1 — бедная', '3': '3 — стандарт', '5': '5 — богатая'}
        field['options'] = [{'value': v, 'label': labels.get(v, v)} for v in expand(spec)]
        field.pop('range', None)
    if spec.default_value:
        field['default'] = spec.default_value
    if extra:
        field.update(extra)
    return field
