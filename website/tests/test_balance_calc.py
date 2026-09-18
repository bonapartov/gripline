"""
Тесты формул калькулятора развесовки (website/services/balance_calc.py).
ТЗ раздел 3.6: тесты формул — часть критериев готовности Блоков 2 И 4, не
отдельный этап. Классы Ballast*/CenterOfGravity* закрывают ту часть 3.6,
которая раньше была отложена до появления Блока 4 (распределение груза,
CG) — самих формул до него не было, тестировать было нечего.

Стиль — как analytics/tests/test_models.py (unittest.TestCase), но там
считают над DataFrame и в БД не ходят вообще, а classify_*/evaluate_setup/
target_center_of_gravity здесь читают BalanceThreshold — для этих классов
используется django.test.TestCase (транзакция откатывается после каждого
теста), не голый unittest.
"""
import unittest
from decimal import Decimal

from django.test import TestCase

from website.models import (
    BalanceDiagnosticRule,
    BalanceThreshold,
    Chassis,
    ChassisTypePreset,
    Driver,
    Kart,
    KartClass,
    Setup,
)
from website.services.balance_calc import (
    apply_ballasts,
    ballast_deltas,
    center_of_gravity,
    classify_all,
    classify_metric,
    compare_setups,
    compute_metrics,
    diagnose,
    evaluate_setup,
    kart_only_weight,
    load_diagnostic_rules,
    min_weight_status,
    target_center_of_gravity,
    validate_ballast_weight,
    validate_corners,
)

D = Decimal


class ComputeMetricsTests(unittest.TestCase):
    """Чистая математика — БД не трогает."""

    def test_reference_43_57_split(self):
        # 43/57 перед/зад, ровно по бортам — стартовая точка ТЗ 3.2.
        metrics = compute_metrics(D("21.5"), D("21.5"), D("28.5"), D("28.5"))
        self.assertEqual(metrics["total_kg"], D("100.0"))
        self.assertEqual(metrics["front_pct"], D("43.0"))
        self.assertEqual(metrics["rear_pct"], D("57.0"))
        self.assertEqual(metrics["left_pct"], D("50.0"))
        self.assertEqual(metrics["right_pct"], D("50.0"))
        self.assertEqual(metrics["cross_pct"], D("50.0"))

    def test_percentage_pairs_always_sum_to_100(self):
        # ТЗ 3.6: «проверка, что сумма долей всегда даёт 100%» — включая
        # противоположную диагональ (LF+RR), которую отдельно не показываем.
        lf, rf, lr, rr = D("32.4"), D("29.1"), D("27.8"), D("31.7")
        metrics = compute_metrics(lf, rf, lr, rr)
        self.assertEqual(metrics["front_pct"] + metrics["rear_pct"], D("100.0"))
        self.assertEqual(metrics["left_pct"] + metrics["right_pct"], D("100.0"))
        total = lf + rf + lr + rr
        opposite_diagonal_pct = float((lf + rr) / total * 100)
        self.assertAlmostEqual(float(metrics["cross_pct"]) + opposite_diagonal_pct, 100.0, places=1)

    def test_asymmetric_input(self):
        metrics = compute_metrics(D("30"), D("25"), D("20"), D("25"))
        self.assertEqual(metrics["total_kg"], D("100.0"))
        self.assertEqual(metrics["front_pct"], D("55.0"))
        self.assertEqual(metrics["rear_pct"], D("45.0"))
        self.assertEqual(metrics["left_pct"], D("50.0"))
        self.assertEqual(metrics["right_pct"], D("50.0"))
        self.assertEqual(metrics["cross_pct"], D("45.0"))

    def test_zero_total_raises(self):
        with self.assertRaises(ValueError):
            compute_metrics(D("0"), D("0"), D("0"), D("0"))


class ValidateCornersTests(unittest.TestCase):

    def test_all_four_required(self):
        result = validate_corners(D("30"), D("30"), None, D("30"))
        self.assertTrue(result["errors"])

    def test_zero_or_negative_blocks(self):
        self.assertTrue(validate_corners(D("30"), D("0"), D("30"), D("30"))["errors"])
        self.assertTrue(validate_corners(D("30"), D("-5"), D("30"), D("30"))["errors"])

    def test_valid_input_has_no_errors(self):
        result = validate_corners(D("30"), D("30"), D("28"), D("28"))
        self.assertEqual(result["errors"], [])

    def test_plausibility_warning_needs_kart_class(self):
        # Половина минималки (40) — 20; угол 30 больше порога -> предупреждение.
        kc = KartClass(name="__t__", slug="__t__", chassis_type="junior", min_weight_kg=D("40"))
        result = validate_corners(D("30"), D("5"), D("5"), D("5"), kart_class=kc)
        self.assertTrue(any("подозрительно" in w for w in result["warnings"]))

    def test_no_plausibility_warning_without_kart_class(self):
        # Без класса эвристику применять не к чему — осознанно не выдумываем
        # глобальный порог "на глаз" (см. docstring validate_corners).
        result = validate_corners(D("30"), D("30"), D("30"), D("30"))
        self.assertEqual(result["warnings"], [])

    def test_total_mismatch_with_min_weight_warns(self):
        kc = KartClass(name="__t2__", slug="__t2__", chassis_type="senior", min_weight_kg=D("150"))
        result = validate_corners(D("10"), D("10"), D("10"), D("10"), kart_class=kc)  # total=40 < 150*0.5
        self.assertTrue(any("расходится" in w for w in result["warnings"]))


class MinWeightAndDriverWeightTests(unittest.TestCase):

    def test_min_weight_none_without_class(self):
        self.assertIsNone(min_weight_status(D("100.0"), None))

    def test_min_weight_margin_positive(self):
        kc = KartClass(min_weight_kg=D("95"))
        status = min_weight_status(D("100.0"), kc)
        self.assertEqual(status["margin_kg"], D("5.0"))
        self.assertFalse(status["is_under"])

    def test_min_weight_shortfall(self):
        kc = KartClass(min_weight_kg=D("110"))
        status = min_weight_status(D("100.0"), kc)
        self.assertEqual(status["margin_kg"], D("-10.0"))
        self.assertTrue(status["is_under"])

    def test_kart_only_weight(self):
        self.assertEqual(kart_only_weight(D("100.0"), D("45.0")), D("55.0"))
        self.assertIsNone(kart_only_weight(D("100.0"), None))


class ClassifyTests(TestCase):
    """Читает BalanceThreshold — реальная таблица порогов из Блока 1."""

    def setUp(self):
        BalanceThreshold.objects.create(
            metric="front_rear", green_min=D("42.5"), green_max=D("43.5"),
            yellow_min=D("42.0"), yellow_max=D("44.0"),
        )
        BalanceThreshold.objects.create(
            metric="left_right", green_min=D("49.5"), green_max=D("50.5"),
            yellow_min=D("49.0"), yellow_max=D("51.0"),
        )
        BalanceThreshold.objects.create(
            metric="cross_weight", green_min=D("49.5"), green_max=D("50.5"),
            yellow_min=D("48.0"), yellow_max=D("52.0"),
        )

    def test_classify_green(self):
        self.assertEqual(classify_metric("front_rear", D("43.0")), "green")

    def test_classify_yellow(self):
        self.assertEqual(classify_metric("front_rear", D("43.8")), "yellow")

    def test_classify_red(self):
        self.assertEqual(classify_metric("front_rear", D("45.0")), "red")

    def test_classify_missing_threshold_returns_none(self):
        BalanceThreshold.objects.all().delete()
        self.assertIsNone(classify_metric("front_rear", D("43.0")))

    def test_classify_all_matches_table_reference_point(self):
        metrics = compute_metrics(D("21.5"), D("21.5"), D("28.5"), D("28.5"))
        result = classify_all(metrics)
        self.assertEqual(result["front_rear"], "green")
        self.assertEqual(result["left_right"], "green")
        self.assertEqual(result["cross_weight"], "green")

    def test_prefetched_thresholds_match_per_query_lookup(self):
        from website.services.balance_calc import load_thresholds
        thresholds = load_thresholds()
        self.assertEqual(
            classify_metric("cross_weight", D("50.0"), thresholds),
            classify_metric("cross_weight", D("50.0")),
        )


class EvaluateSetupTests(TestCase):

    def setUp(self):
        BalanceThreshold.objects.create(
            metric="front_rear", green_min=D("42.5"), green_max=D("43.5"),
            yellow_min=D("42.0"), yellow_max=D("44.0"),
        )

    def test_blocking_error_skips_metrics(self):
        result = evaluate_setup(D("30"), D("0"), D("30"), D("30"))
        self.assertTrue(result["validation"]["errors"])
        self.assertIsNone(result["metrics"])
        self.assertIsNone(result["classification"])

    def test_full_happy_path(self):
        kc = KartClass(name="__t3__", slug="__t3__", chassis_type="junior", min_weight_kg=D("100"))
        result = evaluate_setup(
            D("21.5"), D("21.5"), D("28.5"), D("28.5"),
            kart_class=kc, driver_weight_kg=D("40"),
        )
        self.assertEqual(result["validation"]["errors"], [])
        self.assertEqual(result["metrics"]["total_kg"], D("100.0"))
        self.assertEqual(result["classification"]["front_rear"], "green")
        self.assertEqual(result["min_weight"]["margin_kg"], D("0.0"))
        self.assertEqual(result["kart_only_kg"], D("60.0"))


# ==================== Блок 4 — распределение груза и CG (ТЗ 5.3-5.4) ====================
# Геометрия во всех тестах — круглые числа (wheelbase=track_front=track_rear=1000мм),
# чтобы доли считались в уме и проверялись без плавающей неопределённости.

WHEELBASE = D("1000")
TRACK_F = D("1000")
TRACK_R = D("1000")


class BallastDeltasTests(unittest.TestCase):

    def test_deltas_sum_to_ballast_mass_arbitrary_position(self):
        # ТЗ 3.6: «сумма Δ равна массе груза при любом положении».
        deltas = ballast_deltas(D("10"), D("300"), D("400"), WHEELBASE, TRACK_F, TRACK_R)
        self.assertEqual(deltas["lf"] + deltas["rf"] + deltas["lr"] + deltas["rr"], D("10"))

    def test_center_ballast_is_symmetric(self):
        # ТЗ 3.6: «груз ровно по центру распределяется симметрично».
        deltas = ballast_deltas(D("8"), D("500"), D("500"), WHEELBASE, TRACK_F, TRACK_R)
        self.assertEqual(deltas["lf"], D("2"))
        self.assertEqual(deltas["rf"], D("2"))
        self.assertEqual(deltas["lr"], D("2"))
        self.assertEqual(deltas["rr"], D("2"))

    def test_ballast_exactly_over_front_left_corner(self):
        # ТЗ 3.6: «груз точно над углом даёт всю массу в этот угол».
        deltas = ballast_deltas(D("6"), D("0"), D("0"), WHEELBASE, TRACK_F, TRACK_R)
        self.assertEqual(deltas["lf"], D("6"))
        self.assertEqual(deltas["rf"], D("0"))
        self.assertEqual(deltas["lr"], D("0"))
        self.assertEqual(deltas["rr"], D("0"))

    def test_ballast_exactly_over_rear_right_corner(self):
        deltas = ballast_deltas(D("6"), TRACK_R, WHEELBASE, WHEELBASE, TRACK_F, TRACK_R)
        self.assertEqual(deltas["rr"], D("6"))
        self.assertEqual(deltas["lf"] + deltas["rf"] + deltas["lr"], D("0"))

    def test_negative_ballast(self):
        # ТЗ 3.6: «отрицательный груз работает корректно» — симуляция снятия.
        deltas = ballast_deltas(D("-5"), D("250"), D("250"), WHEELBASE, TRACK_F, TRACK_R)
        self.assertEqual(deltas["lf"] + deltas["rf"] + deltas["lr"] + deltas["rr"], D("-5"))
        self.assertTrue(all(v <= 0 for v in deltas.values()))

    def test_zero_geometry_raises(self):
        with self.assertRaises(ValueError):
            ballast_deltas(D("5"), D("100"), D("100"), D("0"), TRACK_F, TRACK_R)

    def test_ballast_outside_track_extrapolates_without_crashing(self):
        # ТЗ 5.1: «размещение свободное», зоны — подсказка, не ограничение.
        # За пределами колеи формула экстраполирует (доля вне [0,1]) — не
        # блокирует; сумма Δ всё равно остаётся равна массе груза.
        deltas = ballast_deltas(D("10"), D("-200"), D("100"), WHEELBASE, TRACK_F, TRACK_R)
        self.assertEqual(deltas["lf"] + deltas["rf"] + deltas["lr"] + deltas["rr"], D("10"))
        self.assertGreater(deltas["lf"], D("10") * (D("900") / D("1000")))  # доля влево > 1 — за колеёй


class ApplyBallastsTests(unittest.TestCase):

    def setUp(self):
        self.base = {"lf": D("25"), "rf": D("25"), "lr": D("25"), "rr": D("25")}

    def test_add_then_remove_same_ballast_returns_to_base(self):
        # ТЗ 3.6: «пересчёт CG при добавлении/удалении груза» — удаление
        # смоделировано отрицательным грузом в той же точке (ТЗ 2.6/5.2).
        added = apply_ballasts(
            self.base,
            [{"weight_kg": D("10"), "pos_x_mm": D("300"), "pos_y_mm": D("400")}],
            WHEELBASE, TRACK_F, TRACK_R,
        )
        self.assertNotEqual(added, self.base)

        removed = apply_ballasts(
            self.base,
            [
                {"weight_kg": D("10"), "pos_x_mm": D("300"), "pos_y_mm": D("400")},
                {"weight_kg": D("-10"), "pos_x_mm": D("300"), "pos_y_mm": D("400")},
            ],
            WHEELBASE, TRACK_F, TRACK_R,
        )
        self.assertEqual(removed, self.base)

    def test_multiple_ballasts_accumulate(self):
        result = apply_ballasts(
            self.base,
            [
                {"weight_kg": D("4"), "pos_x_mm": D("500"), "pos_y_mm": D("500")},
                {"weight_kg": D("4"), "pos_x_mm": D("500"), "pos_y_mm": D("500")},
            ],
            WHEELBASE, TRACK_F, TRACK_R,
        )
        # Оба груза по центру — симметрично добавляют по 1кг на угол каждый.
        self.assertEqual(result["lf"], D("27.0"))
        self.assertEqual(result["rf"], D("27.0"))
        self.assertEqual(result["lr"], D("27.0"))
        self.assertEqual(result["rr"], D("27.0"))

    def test_no_ballasts_returns_base_unchanged(self):
        self.assertEqual(apply_ballasts(self.base, [], WHEELBASE, TRACK_F, TRACK_R), self.base)


class ValidateBallastWeightTests(unittest.TestCase):

    def test_no_warning_without_kart_class(self):
        self.assertEqual(validate_ballast_weight(D("500")), [])

    def test_warns_on_implausible_weight(self):
        kc = KartClass(name="__t4__", slug="__t4__", chassis_type="junior", min_weight_kg=D("100"))
        self.assertTrue(validate_ballast_weight(D("60"), kart_class=kc))

    def test_no_warning_within_plausible_range(self):
        kc = KartClass(name="__t5__", slug="__t5__", chassis_type="junior", min_weight_kg=D("100"))
        self.assertEqual(validate_ballast_weight(D("3"), kart_class=kc), [])

    def test_negative_weight_checked_by_absolute_value(self):
        kc = KartClass(name="__t6__", slug="__t6__", chassis_type="junior", min_weight_kg=D("100"))
        self.assertTrue(validate_ballast_weight(D("-60"), kart_class=kc))


class CenterOfGravityTests(unittest.TestCase):

    def test_symmetric_corners_center_cg(self):
        cg = center_of_gravity(D("25"), D("25"), D("25"), D("25"), WHEELBASE, TRACK_F, TRACK_R)
        self.assertEqual(cg["cg_along_mm"], D("500"))
        self.assertEqual(cg["cg_across_mm"], D("500"))

    def test_cg_shifts_forward_when_front_heavier(self):
        cg = center_of_gravity(D("40"), D("40"), D("10"), D("10"), WHEELBASE, TRACK_F, TRACK_R)
        self.assertLess(cg["cg_along_mm"], D("500"))

    def test_cg_recalculates_after_adding_ballast(self):
        base = {"lf": D("25"), "rf": D("25"), "lr": D("25"), "rr": D("25")}
        cg_before = center_of_gravity(**base, wheelbase_mm=WHEELBASE, track_front_mm=TRACK_F, track_rear_mm=TRACK_R)

        with_ballast = apply_ballasts(
            base, [{"weight_kg": D("20"), "pos_x_mm": D("0"), "pos_y_mm": D("0")}],  # тяжёлый груз в LF
            WHEELBASE, TRACK_F, TRACK_R,
        )
        cg_after = center_of_gravity(**with_ballast, wheelbase_mm=WHEELBASE, track_front_mm=TRACK_F, track_rear_mm=TRACK_R)

        self.assertLess(cg_after["cg_along_mm"], cg_before["cg_along_mm"])  # сместился к переду
        self.assertLess(cg_after["cg_across_mm"], cg_before["cg_across_mm"])  # и влево

    def test_zero_total_raises(self):
        with self.assertRaises(ValueError):
            center_of_gravity(D("0"), D("0"), D("0"), D("0"), WHEELBASE, TRACK_F, TRACK_R)


class TargetCenterOfGravityTests(TestCase):

    def test_fallback_without_thresholds(self):
        # Без порогов в БД — фолбэк на буквальные 43/57 + 50/50 из ТЗ 3.2.
        target = target_center_of_gravity(WHEELBASE, TRACK_F, TRACK_R)
        self.assertEqual(target["cg_along_mm"], D("570.0"))  # 57% от 1000
        self.assertEqual(target["cg_across_mm"], D("500.0"))  # 50% от 1000

    def test_derives_from_configured_thresholds_not_just_default(self):
        # Пороги сознательно НЕ совпадают с дефолтом 43/50 — доказываем, что
        # целевая точка реально читается из БД, а не просто случайно похожа
        # на фолбэк.
        BalanceThreshold.objects.create(
            metric="front_rear", green_min=D("39.0"), green_max=D("41.0"),  # середина 40
            yellow_min=D("38.0"), yellow_max=D("42.0"),
        )
        BalanceThreshold.objects.create(
            metric="left_right", green_min=D("46.0"), green_max=D("48.0"),  # середина 47
            yellow_min=D("45.0"), yellow_max=D("49.0"),
        )
        target = target_center_of_gravity(WHEELBASE, TRACK_F, TRACK_R)
        self.assertEqual(target["cg_along_mm"], D("600.0"))  # 60% (100-40) от 1000
        self.assertEqual(target["cg_across_mm"], D("470.0"))  # 47% от 1000


# ==================== Блок 6 — диагностика (ТЗ 7.1) ====================

DIAGNOSTIC_CONDITIONS = (
    "front_high", "front_low", "cross_diagonal", "cross_mechanical",
    "lr_asymmetry", "wet_weather", "under_min_weight",
)


class DiagnoseTests(TestCase):

    def setUp(self):
        self.thresholds = {
            "front_rear": BalanceThreshold.objects.create(
                metric="front_rear", green_min=D("42.5"), green_max=D("43.5"),
                yellow_min=D("42.0"), yellow_max=D("44.0"),
            ),
            "left_right": BalanceThreshold.objects.create(
                metric="left_right", green_min=D("49.5"), green_max=D("50.5"),
                yellow_min=D("49.0"), yellow_max=D("51.0"),
            ),
            "cross_weight": BalanceThreshold.objects.create(
                metric="cross_weight", green_min=D("49.5"), green_max=D("50.5"),
                yellow_min=D("48.0"), yellow_max=D("52.0"),
            ),
        }
        for condition in DIAGNOSTIC_CONDITIONS:
            text = "[under_min_weight] {shortfall_kg}" if condition == "under_min_weight" else "[" + condition + "]"
            BalanceDiagnosticRule.objects.create(condition=condition, text=text)
        self.rules = load_diagnostic_rules()

    def _diagnose(self, lf, rf, lr, rr, weather=None, min_weight_kg=None):
        metrics = compute_metrics(lf, rf, lr, rr)
        classification = classify_all(metrics, self.thresholds)
        kart_class = KartClass(min_weight_kg=min_weight_kg) if min_weight_kg is not None else None
        min_weight = min_weight_status(metrics["total_kg"], kart_class)
        conditions = diagnose(
            metrics, classification, min_weight,
            thresholds=self.thresholds, weather=weather, rules=self.rules,
        )
        return [c["condition"] for c in conditions], conditions

    def test_all_green_triggers_nothing(self):
        conditions, _ = self._diagnose(D("21.5"), D("21.5"), D("28.5"), D("28.5"))
        self.assertEqual(conditions, [])

    def test_front_high(self):
        conditions, _ = self._diagnose(D("22.5"), D("22.5"), D("27.5"), D("27.5"))  # front=45%
        self.assertIn("front_high", conditions)
        self.assertNotIn("front_low", conditions)

    def test_front_low(self):
        conditions, _ = self._diagnose(D("19"), D("19"), D("31"), D("31"))  # front=38%
        self.assertIn("front_low", conditions)
        self.assertNotIn("front_high", conditions)

    def test_cross_yellow_at_normal_lr_triggers_diagonal_not_mechanical(self):
        # front=43/57, left/right=50/50, cross=51% (жёлтый, не красный)
        conditions, _ = self._diagnose(D("21"), D("22"), D("29"), D("28"))
        self.assertIn("cross_diagonal", conditions)
        self.assertNotIn("cross_mechanical", conditions)

    def test_cross_red_at_normal_lr_triggers_both(self):
        # front=43/57, left/right=50/50, cross=45% (красный, вне 48-52)
        conditions, _ = self._diagnose(D("24"), D("19"), D("26"), D("31"))
        self.assertIn("cross_diagonal", conditions)
        self.assertIn("cross_mechanical", conditions)

    def test_cross_red_with_lr_also_red_skips_diagonal(self):
        # L/R сам по себе не "нормальный" — диагональ не при чём, это общая
        # асимметрия по бортам; but механика всё равно проверяется.
        conditions, _ = self._diagnose(D("35"), D("5"), D("35"), D("25"))
        self.assertIn("lr_asymmetry", conditions)
        self.assertIn("cross_mechanical", conditions)
        self.assertNotIn("cross_diagonal", conditions)

    def test_wet_weather_only_when_wet(self):
        conditions_none, _ = self._diagnose(D("21.5"), D("21.5"), D("28.5"), D("28.5"), weather=None)
        conditions_dry, _ = self._diagnose(D("21.5"), D("21.5"), D("28.5"), D("28.5"), weather="dry")
        conditions_wet, _ = self._diagnose(D("21.5"), D("21.5"), D("28.5"), D("28.5"), weather="wet")
        self.assertNotIn("wet_weather", conditions_none)
        self.assertNotIn("wet_weather", conditions_dry)
        self.assertIn("wet_weather", conditions_wet)

    def test_under_min_weight_substitutes_shortfall(self):
        conditions, details = self._diagnose(
            D("21.5"), D("21.5"), D("28.5"), D("28.5"), min_weight_kg=D("110"),
        )
        self.assertIn("under_min_weight", conditions)
        entry = [c for c in details if c["condition"] == "under_min_weight"][0]
        self.assertEqual(entry["text"], "[under_min_weight] 10.0")

    def test_no_min_weight_status_skips_rule(self):
        conditions, _ = self._diagnose(D("21.5"), D("21.5"), D("28.5"), D("28.5"), min_weight_kg=None)
        self.assertNotIn("under_min_weight", conditions)

    def test_missing_rule_silently_skips(self):
        metrics = compute_metrics(D("22.5"), D("22.5"), D("27.5"), D("27.5"))
        classification = classify_all(metrics, self.thresholds)
        conditions = diagnose(metrics, classification, None, thresholds=self.thresholds, rules={})
        self.assertEqual(conditions, [])

    def test_article_defaults_to_none(self):
        # Открытый вопрос ТЗ №10 — какая статья Матчасти куда ведёт, ещё не
        # решено; ни одно правило изначально не привязано к статье, и
        # diagnose() должен отдавать это как None, а не падать.
        _, details = self._diagnose(D("22.5"), D("22.5"), D("27.5"), D("27.5"))
        entry = [c for c in details if c["condition"] == "front_high"][0]
        self.assertIsNone(entry["article"])

    def test_order_matches_tz_table(self):
        # Максимально плохой сетап — срабатывает почти всё сразу (включая
        # front_low: 35+5=40% < жёлтой границы 42%); порядок в результате
        # должен соответствовать порядку таблицы ТЗ 7.1.
        conditions, _ = self._diagnose(
            D("35"), D("5"), D("35"), D("25"), weather="wet", min_weight_kg=D("200"),
        )
        expected_order = ["front_low", "cross_mechanical", "lr_asymmetry", "wet_weather", "under_min_weight"]
        self.assertEqual(conditions, expected_order)


# ==================== Блок 7 — сравнение сетапов (ТЗ 8.1) ====================

class CompareSetupsTests(TestCase):
    """website/services/balance_calc.py::compare_setups — дельты + подсветка
    значимых изменений + бонусный сценарий "тот же карт, другой класс"."""

    def setUp(self):
        ChassisTypePreset.objects.create(
            chassis_type="junior", wheelbase_mm=1000, track_front_mm=800, track_rear_mm=850,
        )
        ChassisTypePreset.objects.create(
            chassis_type="senior", wheelbase_mm=1040, track_front_mm=820, track_rear_mm=870,
        )
        self.chassis = Chassis.objects.create(name="__cmp_chassis__")
        self.kart_class = KartClass.objects.create(
            name="__cmp_junior__", slug="__cmp_junior__", chassis_type="junior", min_weight_kg=D("100"),
        )
        self.kart_class_senior = KartClass.objects.create(
            name="__cmp_senior__", slug="__cmp_senior__", chassis_type="senior", min_weight_kg=D("150"),
        )
        driver = Driver.objects.create(first_name="Т", last_name="Т", slug="__cmp_driver__")
        self.kart = Kart.objects.create(
            name="__cmp_kart__", chassis=self.chassis, chassis_type="junior", owner_driver=driver,
        )
        self.other_kart = Kart.objects.create(
            name="__cmp_kart_2__", chassis=self.chassis, chassis_type="junior", owner_driver=driver,
        )
        BalanceThreshold.objects.create(
            metric="front_rear", green_min=D("42.5"), green_max=D("43.5"),
            yellow_min=D("42.0"), yellow_max=D("44.0"),
        )
        BalanceThreshold.objects.create(
            metric="left_right", green_min=D("49.5"), green_max=D("50.5"),
            yellow_min=D("49.0"), yellow_max=D("51.0"),
        )
        BalanceThreshold.objects.create(
            metric="cross_weight", green_min=D("49.5"), green_max=D("50.5"),
            yellow_min=D("48.0"), yellow_max=D("52.0"),
        )

    def _setup(self, kart=None, kart_class=None, **overrides):
        defaults = dict(
            kart=kart or self.kart, name="Setup", kart_class=kart_class or self.kart_class,
            weight_lf=D("21.5"), weight_rf=D("21.5"), weight_lr=D("28.5"), weight_rr=D("28.5"),
        )
        defaults.update(overrides)
        return Setup.objects.create(**defaults)

    def test_identical_setups_have_zero_deltas_and_nothing_significant(self):
        a = self._setup()
        b = self._setup()
        result = compare_setups(a, b)
        for row in result["corners"] + result["metrics"]:
            self.assertEqual(row["delta"], D("0.0"))
            self.assertFalse(row["significant"])

    def test_corner_delta_direction_and_magnitude(self):
        a = self._setup(weight_lf=D("20.0"))
        b = self._setup(weight_lf=D("22.0"))
        result = compare_setups(a, b)
        lf_row = next(r for r in result["corners"] if r["label"] == "Левый перед")
        self.assertEqual(lf_row["delta"], D("2.0"))
        self.assertTrue(lf_row["significant"])

    def test_small_delta_below_threshold_not_significant(self):
        a = self._setup(weight_lf=D("21.5"))
        b = self._setup(weight_lf=D("21.7"))  # 0.2 кг — ниже порога значимости 0.5 кг
        result = compare_setups(a, b)
        lf_row = next(r for r in result["corners"] if r["label"] == "Левый перед")
        self.assertEqual(lf_row["delta"], D("0.2"))
        self.assertFalse(lf_row["significant"])

    def test_classification_change_marked_significant_even_with_tiny_delta(self):
        # 43.4% (зелёная зона 42.5-43.5) -> 43.6% (жёлтая) — дельта копеечная,
        # но пересекает границу зоны, поэтому должна быть отмечена значимой.
        a = self._setup(weight_lf=D("21.7"), weight_rf=D("21.7"), weight_lr=D("28.3"), weight_rr=D("28.3"))
        b = self._setup(weight_lf=D("21.8"), weight_rf=D("21.8"), weight_lr=D("28.2"), weight_rr=D("28.2"))
        result = compare_setups(a, b)
        front_row = next(r for r in result["metrics"] if r["label"] == "Перед")
        self.assertNotEqual(front_row["class_a"], front_row["class_b"])
        self.assertTrue(front_row["significant"])

    def test_kart_only_present_only_when_both_have_driver_weight(self):
        a = self._setup(driver_weight_kg=D("60"))
        b_no_weight = self._setup(driver_weight_kg=None)
        self.assertIsNone(compare_setups(a, b_no_weight)["kart_only"])

        b_with_weight = self._setup(driver_weight_kg=D("65"))
        result = compare_setups(a, b_with_weight)
        self.assertIsNotNone(result["kart_only"])
        # Тот же суммарный вес карта (100 кг), но пилот Б тяжелее на 5 кг ->
        # вес "карт без пилота" у Б меньше на те же 5 кг.
        self.assertEqual(result["kart_only"]["delta"], D("-5.0"))

    def test_same_kart_flag(self):
        a = self._setup(kart=self.kart)
        b = self._setup(kart=self.kart)
        c = self._setup(kart=self.other_kart)
        self.assertTrue(compare_setups(a, b)["same_kart"])
        self.assertFalse(compare_setups(a, c)["same_kart"])

    def test_class_changed_bonus_scenario(self):
        # ТЗ 8.1: "как менялась развесовка этого шасси при переходе из
        # Юниора в Макс" — тот же карт, разные классы.
        a = self._setup(kart=self.kart, kart_class=self.kart_class)
        b = Setup.objects.create(
            kart=self.kart, name="Senior setup", kart_class=self.kart_class_senior,
            weight_lf=D("30"), weight_rf=D("30"), weight_lr=D("40"), weight_rr=D("40"),
        )
        result = compare_setups(a, b)
        self.assertTrue(result["same_kart"])
        self.assertTrue(result["class_changed"])

    def test_different_kart_class_changed_but_not_same_kart(self):
        a = self._setup(kart=self.kart, kart_class=self.kart_class)
        b = self._setup(kart=self.other_kart, kart_class=self.kart_class_senior)
        result = compare_setups(a, b)
        self.assertFalse(result["same_kart"])
        self.assertTrue(result["class_changed"])
