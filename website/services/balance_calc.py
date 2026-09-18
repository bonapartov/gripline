"""
Формулы калькулятора развесовки (ТЗ «Сервис расчёта развесовки карта»,
Блок 2, раздел 3.1-3.5). Канонический серверный расчёт — источник истины
для диагностики (Блок 6) и будущего Flutter/FastAPI слоя (ТЗ раздел 15,
«расчётный слой дублируется на клиенте»). Живой интерактивный ввод на
странице считает те же формулы в JS (balance-calculator.js) — без похода
на сервер на каждое нажатие клавиши; этот модуль — не для того цикла, а
для всего, что требует БД (пороги, классы) или рендерится на сервере.

Все веса — Decimal (поля модели DecimalField, шаг 0.1 кг).
"""
from decimal import Decimal, ROUND_HALF_UP

from website.models import BalanceDiagnosticRule, BalanceThreshold

CORNER_LABELS = {
    "lf": "левый перед",
    "rf": "правый перед",
    "lr": "левый зад",
    "rr": "правый зад",
}


def _round1(value):
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def validate_corners(lf, rf, lr, rr, kart_class=None):
    """
    Список ошибок/предупреждений по угловым весам (ТЗ 3.5). Не бросает
    исключение — вызывающая сторона решает, что делать. 'errors' — расчёт
    не должен выполняться (ноль/отрицательное значение, не все 4 заполнены);
    'warnings' — расчёт можно показать, но с пометкой о вероятной ошибке
    ввода.

    Верхняя граница правдоподобия и сверка с минималкой класса работают
    только если передан kart_class с заполненным min_weight_kg — открытый
    вопрос ТЗ №13 закрыт по собственной эвристике документа: «предупреждать
    при угле выше половины минимального веса класса». Без выбранного класса
    (анонимный расчёт без класса) эти два предупреждения просто не
    появляются — придумывать глобальный порог "на глаз" не стал, реальных
    цифр по классам в справочнике ещё нет.
    """
    errors = []
    warnings = []

    corners = {"lf": lf, "rf": rf, "lr": lr, "rr": rr}
    for key, value in corners.items():
        if value is None:
            errors.append(f"Не заполнен угол «{CORNER_LABELS[key]}» — обязательны все четыре.")
        elif value <= 0:
            errors.append(f"«{CORNER_LABELS[key]}» должен быть больше нуля.")

    if errors:
        return {"errors": errors, "warnings": warnings}

    if kart_class is not None and kart_class.min_weight_kg:
        min_w = kart_class.min_weight_kg
        plausible_max = min_w / 2
        for key, value in corners.items():
            if value > plausible_max:
                warnings.append(
                    f"«{CORNER_LABELS[key]}» ({value} кг) выглядит подозрительно много "
                    f"для класса «{kart_class.name}» — проверьте ввод."
                )

        total = lf + rf + lr + rr
        if total < min_w * Decimal("0.5") or total > min_w * Decimal("1.5"):
            warnings.append(
                f"Суммарный вес {total} кг сильно расходится с минималкой класса "
                f"«{kart_class.name}» ({min_w} кг) — возможна ошибка ввода."
            )

    return {"errors": errors, "warnings": warnings}


def compute_metrics(lf, rf, lr, rr):
    """
    Total/Front/Rear/Left/Right/Cross % — ТЗ 3.1. Предполагает уже
    провалидированные положительные углы (см. validate_corners) — сама
    формул не проверяет, только считает.
    """
    total = lf + rf + lr + rr
    if total <= 0:
        raise ValueError("Сумма угловых весов должна быть положительной.")

    def pct(part):
        return _round1(part / total * Decimal(100))

    return {
        "total_kg": _round1(total),
        "front_pct": pct(lf + rf),
        "rear_pct": pct(lr + rr),
        "left_pct": pct(lf + lr),
        "right_pct": pct(rf + rr),
        "cross_pct": pct(rf + lr),
    }


def load_thresholds():
    return {t.metric: t for t in BalanceThreshold.objects.all()}


def classify_metric(metric_key, value, thresholds=None):
    """'green'/'yellow'/'red', либо None если порог для этой метрики ещё не
    заведён в админке («Развесовка» → «Пороги индикации», Блок 1)."""
    if thresholds is not None:
        threshold = thresholds.get(metric_key)
    else:
        threshold = BalanceThreshold.objects.filter(metric=metric_key).first()
    return threshold.classify(value) if threshold else None


def classify_all(metrics, thresholds=None):
    """
    Классификация ровно по трём независимым метрикам — front, left, cross.
    Rear/right в отдельной классификации не нуждаются: они дополняют
    front/left до 100%, а таблица порогов (ТЗ 3.2) описывает только одну
    строку на пару («Front %», «Left/Right %») — в интерфейсе rear/right
    просто показывают тот же цвет, что и их пара.
    """
    if thresholds is None:
        thresholds = load_thresholds()
    return {
        "front_rear": classify_metric("front_rear", metrics["front_pct"], thresholds),
        "left_right": classify_metric("left_right", metrics["left_pct"], thresholds),
        "cross_weight": classify_metric("cross_weight", metrics["cross_pct"], thresholds),
    }


def min_weight_status(total_kg, kart_class):
    """None — если класс не выбран или у него ещё не заполнен min_weight_kg
    (справочник могут не успеть заполнить сразу). margin_kg отрицательный —
    недобор; ТЗ 3.3: предупреждение информационное, расчёт не блокирует."""
    if kart_class is None or not kart_class.min_weight_kg:
        return None
    margin_kg = total_kg - kart_class.min_weight_kg
    return {
        "min_weight_kg": kart_class.min_weight_kg,
        "margin_kg": _round1(margin_kg),
        "is_under": margin_kg < 0,
    }


def kart_only_weight(total_kg, driver_weight_kg):
    """Total − вес пилота (ТЗ 3.1). None, если вес пилота не задан."""
    if driver_weight_kg is None:
        return None
    return _round1(total_kg - driver_weight_kg)


def evaluate_setup(lf, rf, lr, rr, kart_class=None, driver_weight_kg=None, thresholds=None):
    """
    Единая точка входа для view: валидация → расчёт → классификация →
    проверка минималки → вес карта без пилота. Если есть блокирующие
    ошибки — метрики не считаются вовсе (ТЗ 3.5: «расчёт при трёх
    заполненных не выполняется», то же для нуля/отрицательного значения).
    """
    validation = validate_corners(lf, rf, lr, rr, kart_class=kart_class)
    if validation["errors"]:
        return {
            "validation": validation,
            "metrics": None,
            "classification": None,
            "min_weight": None,
            "kart_only_kg": None,
        }

    metrics = compute_metrics(lf, rf, lr, rr)
    return {
        "validation": validation,
        "metrics": metrics,
        "classification": classify_all(metrics, thresholds=thresholds),
        "min_weight": min_weight_status(metrics["total_kg"], kart_class),
        "kart_only_kg": kart_only_weight(metrics["total_kg"], driver_weight_kg),
    }


# ==================== Блок 4 — визуальный редактор (ТЗ 5.3-5.4) ====================
#
# Груз в точке (x, y): x — от левого края, y — от передней оси. Формула
# использует "x_front"/"x_rear" с разными колеями в знаменателе — по тексту
# ТЗ это не два разных измерения, а один и тот же offset от левого края,
# нормированный то по track_front, то по track_rear (два поперечных сечения
# одной и той же продольной точки). Поэтому pos_x_mm передаётся в обе доли
# без изменений — отличается только знаменатель.

DEFAULT_TARGET_FRONT_PCT = Decimal("43.0")
DEFAULT_TARGET_LEFT_PCT = Decimal("50.0")


def ballast_deltas(weight_kg, pos_x_mm, pos_y_mm, wheelbase_mm, track_front_mm, track_rear_mm):
    """ΔLF/ΔRF/ΔLR/ΔRR для одного груза (ТЗ 5.3). weight_kg может быть
    отрицательным (симуляция снятия). Геометрия должна быть положительной —
    это ответственность вызывающей стороны (см. модуль view/JS): без неё
    редактор балласта в принципе не может работать, недостаточно просто
    промолчать нулями."""
    if wheelbase_mm <= 0 or track_front_mm <= 0 or track_rear_mm <= 0:
        raise ValueError("Геометрия (база и обе колеи) должна быть положительной.")

    front_share = (wheelbase_mm - pos_y_mm) / wheelbase_mm
    rear_share = pos_y_mm / wheelbase_mm

    left_front_share = (track_front_mm - pos_x_mm) / track_front_mm
    left_rear_share = (track_rear_mm - pos_x_mm) / track_rear_mm

    # Не округляем здесь: front_share+rear_share=1 и left_*_share+(1-left_*_share)=1
    # по построению, поэтому сумма всех четырёх Δ должна давать ровно
    # weight_kg (ТЗ 3.6) — округление по одному углу за раз это ломает.
    # Округление — только в apply_ballasts, после суммирования по всем грузам.
    return {
        "lf": weight_kg * front_share * left_front_share,
        "rf": weight_kg * front_share * (1 - left_front_share),
        "lr": weight_kg * rear_share * left_rear_share,
        "rr": weight_kg * rear_share * (1 - left_rear_share),
    }


def apply_ballasts(base_corners, ballasts, wheelbase_mm, track_front_mm, track_rear_mm):
    """
    Итоговые угловые веса = базовые + сумма Δ от всех грузов (ТЗ 5.3).
    base_corners — dict lf/rf/lr/rr. ballasts — список dict с ключами
    weight_kg/pos_x_mm/pos_y_mm (например Ballast.objects.values(...) или
    состояние JS-редактора, сериализованное на сервер).
    """
    totals = {key: Decimal(value) for key, value in base_corners.items()}
    for ballast in ballasts:
        deltas = ballast_deltas(
            Decimal(ballast["weight_kg"]), Decimal(ballast["pos_x_mm"]), Decimal(ballast["pos_y_mm"]),
            wheelbase_mm, track_front_mm, track_rear_mm,
        )
        for key in ("lf", "rf", "lr", "rr"):
            totals[key] += deltas[key]
    return {key: _round1(value) for key, value in totals.items()}


def validate_ballast_weight(weight_kg, kart_class=None):
    """
    ТЗ 3.5: «Вес груза может быть отрицательным, но по модулю ограничен
    разумным пределом». Число в ТЗ не задано — как и для верхней границы
    угла (открытый вопрос №13), эвристика привязана к min_weight_kg класса,
    а не к придуманной константе; без класса проверка не выполняется (см.
    validate_corners — та же логика, тот же повод).
    """
    if kart_class is None or not kart_class.min_weight_kg:
        return []
    plausible_max = kart_class.min_weight_kg / 2
    if abs(weight_kg) > plausible_max:
        return [f"Груз {weight_kg} кг выглядит подозрительно тяжёлым для класса «{kart_class.name}» — проверьте ввод."]
    return []


def center_of_gravity(lf, rf, lr, rr, wheelbase_mm, track_front_mm, track_rear_mm):
    """
    ТЗ 5.4. CG_вдоль — от передней оси; CG_поперёк — от левого края.
    "track_средняя" в ТЗ не уточняет способ усреднения — берём среднее
    арифметическое track_front/track_rear (тот же track_avg, что и в
    ballast_deltas неявно подразумевается для отображения на схеме).
    """
    total = lf + rf + lr + rr
    if total <= 0:
        raise ValueError("Сумма угловых весов должна быть положительной.")
    track_avg = (track_front_mm + track_rear_mm) / 2
    return {
        "cg_along_mm": _round1((lr + rr) / total * wheelbase_mm),
        "cg_across_mm": _round1((rf + rr) / total * track_avg),
    }


def target_center_of_gravity(wheelbase_mm, track_front_mm, track_rear_mm, thresholds=None):
    """
    Маркер «идеального» CG (ТЗ 5.4) — по тем же целевым % 43/57 + 50/50,
    что и стартовая точка из раздела 3.2. Не хардкодит 43/50: если пороги
    front_rear/left_right уже заведены в админке («Развесовка» → «Пороги
    индикации»), целевая точка — середина их зелёной зоны (42.5-43.5 → 43,
    49.5-50.5 → 50 — числа из самого ТЗ, только не задублированные явно).
    Без порогов — фолбэк на буквальные 43/50 из ТЗ 3.2.
    """
    if thresholds is None:
        thresholds = load_thresholds()

    front_rear = thresholds.get("front_rear")
    target_front_pct = (
        (front_rear.green_min + front_rear.green_max) / 2 if front_rear else DEFAULT_TARGET_FRONT_PCT
    )
    left_right = thresholds.get("left_right")
    target_left_pct = (
        (left_right.green_min + left_right.green_max) / 2 if left_right else DEFAULT_TARGET_LEFT_PCT
    )

    track_avg = (track_front_mm + track_rear_mm) / 2
    target_rear_pct = Decimal("100.0") - target_front_pct
    return {
        "cg_along_mm": _round1(target_rear_pct / Decimal("100.0") * wheelbase_mm),
        "cg_across_mm": _round1(target_left_pct / Decimal("100.0") * track_avg),
    }


# ==================== Блок 6 — диагностика и перелинковка (ТЗ 7.1-7.2) ====================
#
# Условия триггеров переиспользуют УЖЕ настроенную классификацию
# green/yellow/red (BalanceThreshold), а не отдельно захардкоженные 42/44,
# 48/52, 49/51 — если Владимир подвинет порог в админке, синхронно
# сдвигается и то, когда именно появляется диагностический текст. Дублировать
# числа в двух местах означало бы гарантированный дрейф между ними.

def load_diagnostic_rules():
    return {r.condition: r for r in BalanceDiagnosticRule.objects.select_related("article").all()}


def diagnose(metrics, classification, min_weight, thresholds=None, weather=None, rules=None):
    """
    Список сработавших диагностических сообщений (ТЗ 7.1), в порядке таблицы
    ТЗ: перед/зад → cross (диагональ, затем механика) → L/R → погода →
    минималка. Каждый элемент — dict {condition, text, article} (article —
    ArticlePage или None, если ссылка ещё не назначена в админке — открытый
    вопрос ТЗ №10, см. BalanceDiagnosticRule).

    weather — 'dry'/'wet'/'mixed'/None. Блок 5 (контекст сетапа: трасса,
    погода) ещё не подключён к интерфейсу калькулятора — до этого параметр
    всегда None, правило wet_weather просто ни разу не сработает. Это не
    заглушка «на будущее» — сама функция уже полностью рабочая, ей пока
    неоткуда получить значение погоды на странице.

    Правило "why_43_57_target" (обучающий блок, ТЗ 7.2) сюда НЕ входит — оно
    не триггерится метриками, показывается всегда и рендерится отдельно
    (см. balance_views.py) через тот же rules-словарь.
    """
    if thresholds is None:
        thresholds = load_thresholds()
    if rules is None:
        rules = load_diagnostic_rules()

    triggered = []

    def add(condition_key, **format_kwargs):
        rule = rules.get(condition_key)
        if not rule:
            return
        text = rule.text.format(**format_kwargs) if format_kwargs else rule.text
        triggered.append({"condition": condition_key, "text": text, "article": rule.article})

    front_rear = thresholds.get("front_rear")
    if classification.get("front_rear") == "red" and front_rear:
        if metrics["front_pct"] > front_rear.yellow_max:
            add("front_high")
        elif metrics["front_pct"] < front_rear.yellow_min:
            add("front_low")

    lr_class = classification.get("left_right")
    cross_class = classification.get("cross_weight")

    if cross_class == "red":
        add("cross_mechanical")
    # "При нормальном L/R" (ТЗ 7.1) — L/R не красный, то есть сам по себе
    # не выглядит проблемой; тогда отклонение cross от зелёной зоны — это
    # именно диагональ, не общая асимметрия по бортам.
    if cross_class and cross_class != "green" and lr_class != "red":
        add("cross_diagonal")

    if lr_class == "red":
        add("lr_asymmetry")

    if weather == "wet":
        add("wet_weather")

    if min_weight and min_weight["is_under"]:
        add("under_min_weight", shortfall_kg=abs(min_weight["margin_kg"]))

    return triggered


# ==================== Блок 7 — сравнение сетапов (ТЗ 8.1) ====================
#
# "Два сетапа рядом" — обе колонки метрик + дельта по каждой, подсветка
# значимых изменений. ТЗ не задаёт числовой порог значимости — берём кратное
# шага округления полей (0.1 кг / 0.1 п.п.), 5x, чтобы не подсвечивать шум
# единичного округления при вводе, но ловить реальные правки развесовки.
# Смена цвета классификации (green/yellow/red) между А и Б считается
# значимой сама по себе, даже если численная дельта ниже порога — это как
# раз тот случай, когда маленькое число пересекло границу зоны.

SIGNIFICANT_WEIGHT_DELTA_KG = Decimal("0.5")
SIGNIFICANT_PCT_DELTA = Decimal("0.5")

CORNER_ROWS = (
    ("lf", "Левый перед"),
    ("rf", "Правый перед"),
    ("lr", "Левый зад"),
    ("rr", "Правый зад"),
)


def _setup_snapshot(setup, thresholds):
    metrics = compute_metrics(setup.weight_lf, setup.weight_rf, setup.weight_lr, setup.weight_rr)
    return {
        "metrics": metrics,
        "classification": classify_all(metrics, thresholds=thresholds),
        "min_weight": min_weight_status(metrics["total_kg"], setup.kart_class),
        "kart_only_kg": kart_only_weight(metrics["total_kg"], setup.driver_weight_kg),
    }


def compare_setups(setup_a, setup_b, thresholds=None):
    """
    -> dict для шаблона сравнения (balance/compare.html). Считает по уже
    сохранённым Setup, не по сырым углам — оба обязаны быть валидны (это
    гарантирует setup_save при сохранении, повторная validate_corners здесь
    не нужна).

    Бонусный сценарий (ТЗ 8.1: "как менялась развесовка этого шасси при
    переходе из Юниора в Макс") — same_kart/class_changed вычисляются прямо
    из полей объектов, без дополнительных запросов.
    """
    if thresholds is None:
        thresholds = load_thresholds()

    snap_a = _setup_snapshot(setup_a, thresholds)
    snap_b = _setup_snapshot(setup_b, thresholds)

    def row(label, a_value, b_value, unit, class_a=None, class_b=None):
        delta = _round1(b_value - a_value)
        significant = abs(delta) >= (SIGNIFICANT_PCT_DELTA if unit == "%" else SIGNIFICANT_WEIGHT_DELTA_KG)
        if class_a is not None and class_a != class_b:
            significant = True
        return {
            "label": label, "a": a_value, "b": b_value, "delta": delta, "unit": unit,
            "class_a": class_a, "class_b": class_b, "significant": significant,
        }

    corners = [
        row(label, getattr(setup_a, f"weight_{key}"), getattr(setup_b, f"weight_{key}"), "кг")
        for key, label in CORNER_ROWS
    ]

    cls_a, cls_b = snap_a["classification"], snap_b["classification"]
    metrics = [
        row("Итого", snap_a["metrics"]["total_kg"], snap_b["metrics"]["total_kg"], "кг"),
        row("Перед", snap_a["metrics"]["front_pct"], snap_b["metrics"]["front_pct"], "%",
            cls_a["front_rear"], cls_b["front_rear"]),
        row("Зад", snap_a["metrics"]["rear_pct"], snap_b["metrics"]["rear_pct"], "%",
            cls_a["front_rear"], cls_b["front_rear"]),
        row("Слева", snap_a["metrics"]["left_pct"], snap_b["metrics"]["left_pct"], "%",
            cls_a["left_right"], cls_b["left_right"]),
        row("Справа", snap_a["metrics"]["right_pct"], snap_b["metrics"]["right_pct"], "%",
            cls_a["left_right"], cls_b["left_right"]),
        row("Cross weight", snap_a["metrics"]["cross_pct"], snap_b["metrics"]["cross_pct"], "%",
            cls_a["cross_weight"], cls_b["cross_weight"]),
    ]

    kart_only = None
    if snap_a["kart_only_kg"] is not None and snap_b["kart_only_kg"] is not None:
        kart_only = row("Карт без пилота", snap_a["kart_only_kg"], snap_b["kart_only_kg"], "кг")

    return {
        "same_kart": setup_a.kart_id == setup_b.kart_id,
        "class_changed": setup_a.kart_class_id != setup_b.kart_class_id,
        "corners": corners,
        "metrics": metrics,
        "kart_only": kart_only,
        "min_weight_a": snap_a["min_weight"],
        "min_weight_b": snap_b["min_weight"],
    }
