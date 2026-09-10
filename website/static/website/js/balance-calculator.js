/*
 * Калькулятор развесовки (/balance/, Блоки 2 и 4) — расчёт в реальном
 * времени на клиенте, без похода на сервер (ТЗ 3.4). Формулы дублируют
 * website/services/balance_calc.py 1:1 (ТЗ раздел 15: «расчётный слой —
 * чистая математика, дублируется на клиенте»). Меняешь формулу — меняй в
 * обоих местах и синхронно (parity проверена вручную через Node на тех же
 * контрольных значениях, что website/tests/test_balance_calc.py).
 *
 * Блок 2 — 4 угла с весов, базовые метрики. Блок 4 — визуальный редактор
 * балласта поверх тех же метрик: перетаскивание груза на SVG-схеме меняет
 * итоговые угловые веса (база + Δ от грузов), а не только "красивую
 * картинку" — результаты и цветовая индикация ниже пересчитываются из
 * ballast-adjusted весов, если на схеме есть хоть один груз.
 *
 * Пороги (BalanceThreshold) и классы (KartClass, вместе с геометрией через
 * effective_geometry()) прилетают уже посчитанными на сервере через
 * json_script — калькулятор работает и анонимно, в БД сам не лезет.
 */
(function () {
  "use strict";

  function readJson(id, fallback) {
    var el = document.getElementById(id);
    if (!el) return fallback;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return fallback;
    }
  }

  var KART_CLASSES = readJson("balanceKartClasses", []);
  var THRESHOLDS = readJson("balanceThresholds", {});
  var DIAGNOSTIC_RULES = readJson("balanceDiagnosticRules", {});

  var CORNER_LABELS = { lf: "левый перед", rf: "правый перед", lr: "левый зад", rr: "правый зад" };
  var CORNER_KEYS = ["lf", "rf", "lr", "rr"];

  function round1(n) {
    return Math.round(n * 10) / 10;
  }

  function parseWeight(raw) {
    if (raw === undefined || raw === null) return NaN;
    var normalized = String(raw).trim().replace(",", ".");
    if (normalized === "") return NaN;
    return parseFloat(normalized);
  }

  // ── Формулы (Блок 2, ТЗ 3.1-3.5) — 1:1 с balance_calc.py ────────────

  function classify(metricKey, value) {
    var t = THRESHOLDS[metricKey];
    if (!t) return null;
    var gmin = parseFloat(t.green_min), gmax = parseFloat(t.green_max);
    var ymin = parseFloat(t.yellow_min), ymax = parseFloat(t.yellow_max);
    if (value >= gmin && value <= gmax) return "green";
    if (value >= ymin && value <= ymax) return "yellow";
    return "red";
  }

  function validateCorners(corners, kartClass) {
    var errors = [];
    var warnings = [];

    CORNER_KEYS.forEach(function (key) {
      var v = corners[key];
      if (isNaN(v)) {
        errors.push("Не заполнен угол «" + CORNER_LABELS[key] + "» — обязательны все четыре.");
      } else if (v <= 0) {
        errors.push("«" + CORNER_LABELS[key] + "» должен быть больше нуля.");
      }
    });
    if (errors.length) return { errors: errors, warnings: warnings };

    if (kartClass && kartClass.min_weight_kg) {
      var minW = parseFloat(kartClass.min_weight_kg);
      var plausibleMax = minW / 2;
      CORNER_KEYS.forEach(function (key) {
        if (corners[key] > plausibleMax) {
          warnings.push(
            "«" + CORNER_LABELS[key] + "» (" + corners[key] + " кг) выглядит подозрительно много " +
            "для класса «" + kartClass.name + "» — проверьте ввод."
          );
        }
      });
      var total = corners.lf + corners.rf + corners.lr + corners.rr;
      if (total < minW * 0.5 || total > minW * 1.5) {
        warnings.push(
          "Суммарный вес " + round1(total) + " кг сильно расходится с минималкой класса «" +
          kartClass.name + "» (" + minW + " кг) — возможна ошибка ввода."
        );
      }
    }

    return { errors: errors, warnings: warnings };
  }

  function computeMetrics(corners) {
    var lf = corners.lf, rf = corners.rf, lr = corners.lr, rr = corners.rr;
    var total = lf + rf + lr + rr;
    function pct(part) {
      return round1((part / total) * 100);
    }
    return {
      total_kg: round1(total),
      front_pct: pct(lf + rf),
      rear_pct: pct(lr + rr),
      left_pct: pct(lf + lr),
      right_pct: pct(rf + rr),
      cross_pct: pct(rf + lr),
      // % каждого угла от общего веса — презентационное значение для схемы
      // (подпись под угловым инпутом), не входит в канонический набор
      // метрик ТЗ 3.1 и не участвует в classify()/diagnose(), поэтому не
      // дублируется в balance_calc.py — там дублируется только то, что
      // влияет на расчёт/диагностику, не любое производное число для вывода.
      corner_pct: { lf: pct(lf), rf: pct(rf), lr: pct(lr), rr: pct(rr) },
    };
  }

  // Total − вес пилота (ТЗ 3.1, kart_only_weight в balance_calc.py). Здесь —
  // презентационное зеркало для анонимного калькулятора: вес пилота нигде
  // не сохраняется (Блок 3 ещё не собран), поле на клиенте, в БД не летит.
  function kartOnlyWeight(totalKg, driverWeightKg) {
    if (isNaN(driverWeightKg)) return null;
    return round1(totalKg - driverWeightKg);
  }

  function minWeightStatus(totalKg, kartClass) {
    if (!kartClass || !kartClass.min_weight_kg) return null;
    var minW = parseFloat(kartClass.min_weight_kg);
    var margin = round1(totalKg - minW);
    return { min_weight_kg: minW, margin_kg: margin, is_under: margin < 0 };
  }

  // ── Формулы (Блок 4, ТЗ 5.3-5.4) — 1:1 с balance_calc.py ────────────
  // x — от левого края, y — от передней оси. "x_front"/"x_rear" в ТЗ — не
  // два разных измерения, а один и тот же offset от левого края, делённый
  // то на track_front, то на track_rear (см. balance_calc.py).

  function ballastDeltas(weightKg, posXMm, posYMm, wheelbaseMm, trackFrontMm, trackRearMm) {
    var frontShare = (wheelbaseMm - posYMm) / wheelbaseMm;
    var rearShare = posYMm / wheelbaseMm;
    var leftFrontShare = (trackFrontMm - posXMm) / trackFrontMm;
    var leftRearShare = (trackRearMm - posXMm) / trackRearMm;
    return {
      lf: weightKg * frontShare * leftFrontShare,
      rf: weightKg * frontShare * (1 - leftFrontShare),
      lr: weightKg * rearShare * leftRearShare,
      rr: weightKg * rearShare * (1 - leftRearShare),
    };
  }

  function applyBallasts(baseCorners, ballastList, geometry) {
    var totals = { lf: baseCorners.lf, rf: baseCorners.rf, lr: baseCorners.lr, rr: baseCorners.rr };
    ballastList.forEach(function (b) {
      var d = ballastDeltas(b.weight_kg, b.pos_x_mm, b.pos_y_mm, geometry.wheelbaseMm, geometry.trackFrontMm, geometry.trackRearMm);
      totals.lf += d.lf;
      totals.rf += d.rf;
      totals.lr += d.lr;
      totals.rr += d.rr;
    });
    return {
      lf: round1(totals.lf),
      rf: round1(totals.rf),
      lr: round1(totals.lr),
      rr: round1(totals.rr),
    };
  }

  function centerOfGravity(lf, rf, lr, rr, geometry) {
    var total = lf + rf + lr + rr;
    if (total <= 0) return null;
    var trackAvg = (geometry.trackFrontMm + geometry.trackRearMm) / 2;
    return {
      along: round1(((lr + rr) / total) * geometry.wheelbaseMm),
      across: round1(((rf + rr) / total) * trackAvg),
    };
  }

  function targetCenterOfGravity(geometry) {
    var fr = THRESHOLDS.front_rear;
    var targetFrontPct = fr ? (parseFloat(fr.green_min) + parseFloat(fr.green_max)) / 2 : 43.0;
    var lr = THRESHOLDS.left_right;
    var targetLeftPct = lr ? (parseFloat(lr.green_min) + parseFloat(lr.green_max)) / 2 : 50.0;

    var trackAvg = (geometry.trackFrontMm + geometry.trackRearMm) / 2;
    var targetRearPct = 100 - targetFrontPct;
    return {
      along: round1((targetRearPct / 100) * geometry.wheelbaseMm),
      across: round1((targetLeftPct / 100) * trackAvg),
    };
  }

  function validateBallastWeight(weightKg, kartClass) {
    if (!kartClass || !kartClass.min_weight_kg) return [];
    var plausibleMax = parseFloat(kartClass.min_weight_kg) / 2;
    if (Math.abs(weightKg) > plausibleMax) {
      return ["Груз " + weightKg + " кг выглядит подозрительно тяжёлым для класса «" + kartClass.name + "» — проверьте ввод."];
    }
    return [];
  }

  // ── Формулы (Блок 6, ТЗ 7.1) — 1:1 с balance_calc.py::diagnose ──────
  // weather всегда null, пока Блок 5 не добавил выбор погоды в интерфейс —
  // правило wet_weather заведено и рабочее, просто пока неоткуда взять
  // значение. "why_43_57_target" сюда не входит — не триггерится метриками,
  // рендерится отдельно, статически, из context (см. balance_views.py).

  function diagnose(metrics, classification, minWeight, weather) {
    var triggered = [];

    function add(conditionKey, subs) {
      var rule = DIAGNOSTIC_RULES[conditionKey];
      if (!rule) return;
      var text = rule.text;
      if (subs) {
        Object.keys(subs).forEach(function (key) {
          text = text.replace("{" + key + "}", subs[key]);
        });
      }
      triggered.push({ condition: conditionKey, text: text, article_url: rule.article_url, article_title: rule.article_title });
    }

    var frThreshold = THRESHOLDS.front_rear;
    if (classification.front_rear === "red" && frThreshold) {
      if (metrics.front_pct > parseFloat(frThreshold.yellow_max)) {
        add("front_high");
      } else if (metrics.front_pct < parseFloat(frThreshold.yellow_min)) {
        add("front_low");
      }
    }

    var lrClass = classification.left_right;
    var crossClass = classification.cross_weight;

    if (crossClass === "red") add("cross_mechanical");
    if (crossClass && crossClass !== "green" && lrClass !== "red") add("cross_diagonal");
    if (lrClass === "red") add("lr_asymmetry");

    if (weather === "wet") add("wet_weather");

    if (minWeight && minWeight.is_under) {
      add("under_min_weight", { shortfall_kg: Math.abs(minWeight.margin_kg) });
    }

    return triggered;
  }

  // ── DOM wiring — Блок 2 ─────────────────────────────────────────────

  var inputs = {
    lf: document.querySelector('[data-corner="lf"]'),
    rf: document.querySelector('[data-corner="rf"]'),
    lr: document.querySelector('[data-corner="lr"]'),
    rr: document.querySelector('[data-corner="rr"]'),
  };

  if (!inputs.lf) return; // не на странице калькулятора — скрипт молча ничего не делает

  var classSelect = document.getElementById("glCalcClassSelect");
  var weatherSelect = document.getElementById("glCalcWeather");
  var driverWeightInput = document.getElementById("glCalcDriverWeight");
  var messagesEl = document.getElementById("glCalcMessages");
  var minWeightEl = document.getElementById("glCalcMinWeight");
  var diagnosticsEl = document.getElementById("glCalcDiagnostics");
  var ctaEl = document.getElementById("glCalcSaveCta");
  var clearBtn = document.getElementById("glCalcClearBtn");
  var baseBtn = document.getElementById("glCalcBaseBtn");

  // ── Gauge-бар (перед/зад, лево/право) + cross weight + база/итого ────
  var gaugebarEl = document.getElementById("glCalcGaugebar");
  var gaugeFrGroup = document.querySelector(".gl-calc-gauge--fr");
  var gaugeLrGroup = document.querySelector(".gl-calc-gauge--lr");
  var gaugeValues = {
    front: document.querySelector('[data-gauge="front"]'),
    rear: document.querySelector('[data-gauge="rear"]'),
    left: document.querySelector('[data-gauge="left"]'),
    right: document.querySelector('[data-gauge="right"]'),
  };
  var crossEl = document.getElementById("glCalcCross");
  var crossValueEl = document.querySelector('[data-gauge="cross"]');
  var weightRowEl = document.getElementById("glCalcWeightRow");
  var weightBaseItemEl = document.getElementById("glCalcWeightBaseItem");
  var weightBaseValueEl = document.querySelector('[data-weight="base"]');
  var weightTotalValueEl = document.querySelector('[data-weight="total"]');

  function currentKartClass() {
    if (!classSelect || !classSelect.value) return null;
    for (var i = 0; i < KART_CLASSES.length; i++) {
      if (String(KART_CLASSES[i].id) === classSelect.value) return KART_CLASSES[i];
    }
    return null;
  }

  // Погода (Блок 5, ТЗ §6.2) — питает правило wet_weather в diagnose().
  // "mixed" трактуем как сухую базу (рекомендация +1-2% на перед — только
  // для явного дождя).
  function currentWeather() {
    return weatherSelect && weatherSelect.value ? weatherSelect.value : null;
  }

  // ── Аналитика (Блок 10, ТЗ §10.2) — Яндекс.Метрика reachGoal ────────
  // Счётчик общий с gripline.ru (id в balance/app_base.html). ym() может
  // ещё не подняться (блокировщики, медленная сеть) — тихо не шлём.
  var YM_COUNTER = (window.__balanceYmCounter || 0);
  var firedGoals = {};
  function track(goal, params) {
    if (!YM_COUNTER || typeof window.ym !== "function") return;
    try {
      window.ym(YM_COUNTER, "reachGoal", goal, params || undefined);
    } catch (e) { /* аналитика не должна ронять калькулятор */ }
  }
  function trackOnce(goal, params) {
    if (firedGoals[goal]) return;
    firedGoals[goal] = true;
    track(goal, params);
  }

  function renderMessages(validation) {
    if (!messagesEl) return;
    var html = "";
    validation.errors.forEach(function (msg) {
      html += '<div class="gl-calc-message gl-calc-message--error">' + msg + "</div>";
    });
    validation.warnings.forEach(function (msg) {
      html += '<div class="gl-calc-message gl-calc-message--warning">' + msg + "</div>";
    });
    messagesEl.innerHTML = html;
    messagesEl.hidden = !html;
  }

  function setGaugeClass(el, cls) {
    if (!el) return;
    el.classList.remove("gl-calc-gauge--green", "gl-calc-gauge--yellow", "gl-calc-gauge--red");
    if (cls) el.classList.add("gl-calc-gauge--" + cls);
  }

  function renderResults(metrics, classification, kartClass) {
    if (!metrics) {
      if (gaugebarEl) gaugebarEl.hidden = true;
      if (crossEl) crossEl.hidden = true;
      if (weightRowEl) weightRowEl.hidden = true;
      if (minWeightEl) minWeightEl.hidden = true;
      return;
    }

    if (gaugebarEl) {
      gaugebarEl.hidden = false;
      if (gaugeValues.front) gaugeValues.front.textContent = metrics.front_pct + "%";
      if (gaugeValues.rear) gaugeValues.rear.textContent = metrics.rear_pct + "%";
      if (gaugeValues.left) gaugeValues.left.textContent = metrics.left_pct + "%";
      if (gaugeValues.right) gaugeValues.right.textContent = metrics.right_pct + "%";
      setGaugeClass(gaugeFrGroup, classification.front_rear);
      setGaugeClass(gaugeLrGroup, classification.left_right);
    }

    if (crossEl) {
      crossEl.hidden = false;
      if (crossValueEl) crossValueEl.textContent = metrics.cross_pct + "%";
      crossEl.classList.remove("gl-calc-cross--green", "gl-calc-cross--yellow", "gl-calc-cross--red");
      if (classification.cross_weight) crossEl.classList.add("gl-calc-cross--" + classification.cross_weight);
    }

    if (weightRowEl) {
      weightRowEl.hidden = false;
      var driverWeight = parseWeight(driverWeightInput ? driverWeightInput.value : "");
      var baseKg = kartOnlyWeight(metrics.total_kg, driverWeight);
      if (weightBaseItemEl) weightBaseItemEl.hidden = baseKg === null;
      if (weightBaseValueEl && baseKg !== null) weightBaseValueEl.textContent = baseKg + " кг";
      if (weightTotalValueEl) weightTotalValueEl.textContent = metrics.total_kg + " кг";
    }

    if (minWeightEl) {
      var status = minWeightStatus(metrics.total_kg, kartClass);
      if (!status) {
        minWeightEl.hidden = true;
      } else {
        minWeightEl.hidden = false;
        minWeightEl.className = "gl-calc-min-weight" + (status.is_under ? " gl-calc-min-weight--under" : "");
        minWeightEl.textContent = status.is_under
          ? "Недобор до минималки класса: " + Math.abs(status.margin_kg) + " кг (минималка проверяется после заезда — учтите выгорание топлива)"
          : "Запас над минималкой класса: " + status.margin_kg + " кг";
      }
    }
  }

  function renderDiagnostics(items) {
    if (!diagnosticsEl) return;
    if (!items || !items.length) {
      diagnosticsEl.innerHTML = "";
      diagnosticsEl.hidden = true;
      return;
    }
    var html = "";
    items.forEach(function (item) {
      html += '<div class="gl-calc-diagnostic">';
      html += "<p>" + item.text + "</p>";
      if (item.article_url) {
        html += '<a href="' + item.article_url + '" target="_blank" rel="noopener">Подробнее' +
          (item.article_title ? " — " + item.article_title : "") + " →</a>";
      }
      html += "</div>";
    });
    diagnosticsEl.innerHTML = html;
    diagnosticsEl.hidden = false;
  }

  var cornerResults = {
    lf: document.querySelector('[data-corner-result="lf"]'),
    rf: document.querySelector('[data-corner-result="rf"]'),
    lr: document.querySelector('[data-corner-result="lr"]'),
    rr: document.querySelector('[data-corner-result="rr"]'),
  };

  var cornerPercents = {
    lf: document.querySelector('[data-corner-pct="lf"]'),
    rf: document.querySelector('[data-corner-pct="rf"]'),
    lr: document.querySelector('[data-corner-pct="lr"]'),
    rr: document.querySelector('[data-corner-pct="rr"]'),
  };

  // % угла от общего веса — считается из тех же appliedCorners, что и
  // metrics (см. computeMetrics), поэтому вызывается сразу после неё.
  function renderCornerPercents(metrics) {
    CORNER_KEYS.forEach(function (key) {
      var el = cornerPercents[key];
      if (!el) return;
      if (metrics) {
        el.textContent = metrics.corner_pct[key] + "%";
        el.hidden = false;
      } else {
        el.hidden = true;
      }
    });
  }

  // ── DOM wiring — Блок 4 (визуальный редактор балласта) ──────────────
  // Схема одна на весь калькулятор (ТЗ §3.4 + §5.1): те же угловые поля,
  // поверх них — размещение балласта и маркеры CG. Отдельного второго
  // контура карта нет.

  var schemaEl = document.getElementById("glCalcSchema");
  var wheelbaseInput = document.getElementById("glCalcWheelbase");
  var trackFrontInput = document.getElementById("glCalcTrackFront");
  var trackRearInput = document.getElementById("glCalcTrackRear");
  var ballastLockHintEl = document.getElementById("glCalcBallastLockHint");
  var ballastHintEl = document.getElementById("glCalcBallastHint");
  var ballastLegendEl = document.getElementById("glCalcBallastLegend");
  var svg = document.getElementById("glCalcSchemaSvg");
  var markersGroup = document.getElementById("glCalcBallastMarkers");
  var cgActualEl = document.getElementById("glCalcCgActual");
  var cgTargetEl = document.getElementById("glCalcCgTarget");

  var popup = document.getElementById("glCalcBallastPopup");
  var popupWeight = document.getElementById("glCalcBallastWeight");
  var popupLabel = document.getElementById("glCalcBallastLabel");
  var popupSaveBtn = document.getElementById("glCalcBallastSave");
  var popupDeleteBtn = document.getElementById("glCalcBallastDelete");
  var popupCancelBtn = document.getElementById("glCalcBallastCancel");

  // Координаты — центры колёс на трассированной иллюстрации (2026-09-09,
  // viewBox 896×1199), измерены алгоритмически (connected-component поиск
  // серой заливки колеса по бинарной маске исходного PNG), не на глаз:
  // FL (107,288) FR (780,288) RL (71,939) RR (824,939) — left/right усреднены
  // по обеим осям, как и раньше делал один leftEdgePx/rightEdgePx на трек.
  var SCHEMA = { frontAxlePx: 288, rearAxlePx: 939, leftEdgePx: 89, rightEdgePx: 802 };
  SCHEMA.wheelbasePx = SCHEMA.rearAxlePx - SCHEMA.frontAxlePx;
  SCHEMA.trackPx = SCHEMA.rightEdgePx - SCHEMA.leftEdgePx;

  var ballasts = [];
  var nextBallastId = 1;
  var popupState = null; // { mode: 'add'|'edit', ballastId, posXMm, posYMm }

  function currentGeometry() {
    var wheelbase = parseWeight(wheelbaseInput.value);
    var trackFront = parseWeight(trackFrontInput.value);
    var trackRear = parseWeight(trackRearInput.value);
    if (isNaN(wheelbase) || isNaN(trackFront) || isNaN(trackRear)) return null;
    if (wheelbase <= 0 || trackFront <= 0 || trackRear <= 0) return null;
    return { wheelbaseMm: wheelbase, trackFrontMm: trackFront, trackRearMm: trackRear };
  }

  function fillGeometryFromClass(kartClass) {
    if (!kartClass) return;
    if (kartClass.wheelbase_mm) wheelbaseInput.value = kartClass.wheelbase_mm;
    if (kartClass.track_front_mm) trackFrontInput.value = kartClass.track_front_mm;
    if (kartClass.track_rear_mm) trackRearInput.value = kartClass.track_rear_mm;
  }

  function mmToPx(xMm, yMm, geometry) {
    var trackAvg = (geometry.trackFrontMm + geometry.trackRearMm) / 2;
    return {
      x: SCHEMA.leftEdgePx + (xMm / trackAvg) * SCHEMA.trackPx,
      y: SCHEMA.frontAxlePx + (yMm / geometry.wheelbaseMm) * SCHEMA.wheelbasePx,
    };
  }

  function pxToMm(pxX, pxY, geometry) {
    var trackAvg = (geometry.trackFrontMm + geometry.trackRearMm) / 2;
    return {
      x: ((pxX - SCHEMA.leftEdgePx) / SCHEMA.trackPx) * trackAvg,
      y: ((pxY - SCHEMA.frontAxlePx) / SCHEMA.wheelbasePx) * geometry.wheelbaseMm,
    };
  }

  function svgPointFromClient(clientX, clientY) {
    var pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    var ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    var p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  }

  function renderBallastLayerAvailability() {
    var geometry = currentGeometry();
    var available = !!geometry;
    // Схему не прячем никогда — Блок 2 (угловые веса + метрики) от геометрии
    // не зависит. Без геометрии выключается только слой балласта: тап по
    // схеме ничего не добавляет, показывается подсказка внутри контура.
    if (schemaEl) schemaEl.classList.toggle("gl-calc-schema--ballast-locked", !available);
    if (ballastLockHintEl) ballastLockHintEl.hidden = available;
    if (ballastHintEl) ballastHintEl.hidden = !available;
    return geometry;
  }

  function renderBallastMarkers(geometry) {
    if (!markersGroup) return;
    markersGroup.innerHTML = "";
    if (!geometry) return;
    ballasts.forEach(function (b) {
      var px = mmToPx(b.pos_x_mm, b.pos_y_mm, geometry);
      var g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("class", "gl-calc-ballast-marker" + (b.weight_kg < 0 ? " gl-calc-ballast-marker--negative" : ""));
      g.setAttribute("transform", "translate(" + px.x + "," + px.y + ")");
      g.setAttribute("data-ballast-id", String(b.id));

      var hit = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      hit.setAttribute("class", "gl-calc-ballast-marker__hit");
      hit.setAttribute("r", "70");
      g.appendChild(hit);

      var dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("class", "gl-calc-ballast-marker__dot");
      dot.setAttribute("r", "32");
      g.appendChild(dot);

      var text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("class", "gl-calc-ballast-marker__text");
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("dy", "11");
      text.textContent = (b.weight_kg > 0 ? "+" : "") + b.weight_kg;
      g.appendChild(text);

      markersGroup.appendChild(g);
    });
  }

  function renderCgMarkers(appliedCorners, geometry) {
    if (!cgActualEl || !cgTargetEl) return;
    if (!geometry) {
      cgActualEl.hidden = true;
      cgTargetEl.hidden = true;
      return;
    }
    var actual = centerOfGravity(appliedCorners.lf, appliedCorners.rf, appliedCorners.lr, appliedCorners.rr, geometry);
    var target = targetCenterOfGravity(geometry);

    if (actual) {
      var actualPx = mmToPx(actual.across, actual.along, geometry);
      cgActualEl.setAttribute("transform", "translate(" + actualPx.x + "," + actualPx.y + ")");
      cgActualEl.hidden = false;
    } else {
      cgActualEl.hidden = true;
    }

    var targetPx = mmToPx(target.across, target.along, geometry);
    cgTargetEl.setAttribute("transform", "translate(" + targetPx.x + "," + targetPx.y + ")");
    cgTargetEl.hidden = false;
  }

  // Итоговые угловые веса (база + Δ от грузов, ТЗ §5.3) — маленькой строкой
  // под полем ввода, только если груз реально сдвинул угол. Само поле
  // остаётся тем, что снято с весов, — редактируемым.
  function renderCornerResults(baseCorners, appliedCorners) {
    CORNER_KEYS.forEach(function (key) {
      var el = cornerResults[key];
      if (!el) return;
      var base = baseCorners[key];
      if (appliedCorners && !isNaN(base) && Math.abs(appliedCorners[key] - base) >= 0.05) {
        el.textContent = "→ " + round1(appliedCorners[key]);
        el.hidden = false;
      } else {
        el.hidden = true;
      }
    });
  }

  // ── Попап добавления/редактирования груза ───────────────────────────

  function showPopup() {
    if (popup) popup.hidden = false;
    if (popupWeight) popupWeight.focus();
  }

  function hidePopup() {
    if (popup) popup.hidden = true;
    popupState = null;
  }

  function openAddPopup(posXMm, posYMm) {
    popupState = { mode: "add", ballastId: null, posXMm: posXMm, posYMm: posYMm };
    if (popupWeight) popupWeight.value = "";
    if (popupLabel) popupLabel.value = "";
    if (popupDeleteBtn) popupDeleteBtn.hidden = true;
    showPopup();
  }

  function openEditPopup(ballast) {
    popupState = { mode: "edit", ballastId: ballast.id, posXMm: ballast.pos_x_mm, posYMm: ballast.pos_y_mm };
    if (popupWeight) popupWeight.value = String(ballast.weight_kg);
    if (popupLabel) popupLabel.value = ballast.label || "";
    if (popupDeleteBtn) popupDeleteBtn.hidden = false;
    showPopup();
  }

  if (popupSaveBtn) {
    popupSaveBtn.addEventListener("click", function () {
      if (!popupState) return;
      var weight = round1(parseWeight(popupWeight.value));
      if (isNaN(weight) || weight === 0) {
        popupWeight.classList.add("gl-calc-corner--error");
        return;
      }
      popupWeight.classList.remove("gl-calc-corner--error");
      var label = popupLabel ? popupLabel.value.trim() : "";

      if (popupState.mode === "add") {
        ballasts.push({
          id: nextBallastId++,
          weight_kg: weight,
          pos_x_mm: popupState.posXMm,
          pos_y_mm: popupState.posYMm,
          label: label,
        });
      } else {
        var existing = ballasts.filter(function (b) { return b.id === popupState.ballastId; })[0];
        if (existing) {
          existing.weight_kg = weight;
          existing.label = label;
        }
      }
      hidePopup();
      recalc();
      trackOnce("ballast_moved");
    });
  }

  if (popupDeleteBtn) {
    popupDeleteBtn.addEventListener("click", function () {
      if (!popupState || popupState.mode !== "edit") return;
      ballasts = ballasts.filter(function (b) { return b.id !== popupState.ballastId; });
      hidePopup();
      recalc();
    });
  }

  if (popupCancelBtn) {
    popupCancelBtn.addEventListener("click", hidePopup);
  }

  // ── Тап / перетаскивание на схеме (Pointer Events — мышь и тач одним кодом) ──

  var DRAG_THRESHOLD_PX = 6;
  var pointerState = null; // { ballastId|null, startClientX, startClientY, moved }

  if (svg) {
    svg.addEventListener("pointerdown", function (evt) {
      var markerG = evt.target.closest ? evt.target.closest(".gl-calc-ballast-marker") : null;
      var ballastId = markerG ? parseInt(markerG.getAttribute("data-ballast-id"), 10) : null;
      pointerState = {
        ballastId: ballastId,
        startClientX: evt.clientX,
        startClientY: evt.clientY,
        moved: false,
      };
      if (markerG) {
        try { svg.setPointerCapture(evt.pointerId); } catch (e) { /* ignore */ }
      }
    });

    svg.addEventListener("pointermove", function (evt) {
      if (!pointerState || pointerState.ballastId === null) return; // двигаем только существующий груз
      var dx = evt.clientX - pointerState.startClientX;
      var dy = evt.clientY - pointerState.startClientY;
      if (!pointerState.moved && Math.sqrt(dx * dx + dy * dy) < DRAG_THRESHOLD_PX) return;
      pointerState.moved = true;

      var geometry = currentGeometry();
      if (!geometry) return;
      var svgPt = svgPointFromClient(evt.clientX, evt.clientY);
      var mm = pxToMm(svgPt.x, svgPt.y, geometry);
      var ballast = ballasts.filter(function (b) { return b.id === pointerState.ballastId; })[0];
      if (!ballast) return;
      ballast.pos_x_mm = round1(mm.x);
      ballast.pos_y_mm = round1(mm.y);
      recalc();
    });

    svg.addEventListener("pointerup", function (evt) {
      if (!pointerState) return;
      var state = pointerState;
      pointerState = null;

      if (state.ballastId !== null && state.moved) {
        // Перетаскивание существующего груза — удалить, если отпустили за
        // пределами схемы (ТЗ 5.2), иначе позиция уже применена в pointermove.
        var rect = svg.getBoundingClientRect();
        var outside = (
          evt.clientX < rect.left || evt.clientX > rect.right ||
          evt.clientY < rect.top || evt.clientY > rect.bottom
        );
        if (outside) {
          ballasts = ballasts.filter(function (b) { return b.id !== state.ballastId; });
          recalc();
        }
        return;
      }

      // Чистый тап (без значимого движения).
      var geometry = currentGeometry();
      if (!geometry) return;

      if (state.ballastId !== null) {
        var ballast = ballasts.filter(function (b) { return b.id === state.ballastId; })[0];
        if (ballast) openEditPopup(ballast);
        return;
      }

      var svgPt = svgPointFromClient(evt.clientX, evt.clientY);
      var mm = pxToMm(svgPt.x, svgPt.y, geometry);
      openAddPopup(round1(mm.x), round1(mm.y));
    });
  }

  // ── Пересчёт ──────────────────────────────────────────────────────

  function recalc() {
    var corners = {
      lf: parseWeight(inputs.lf.value),
      rf: parseWeight(inputs.rf.value),
      lr: parseWeight(inputs.lr.value),
      rr: parseWeight(inputs.rr.value),
    };

    CORNER_KEYS.forEach(function (key) {
      var invalid = inputs[key].value.trim() !== "" && (isNaN(corners[key]) || corners[key] <= 0);
      inputs[key].classList.toggle("gl-calc-corner--error", invalid);
    });

    var kartClass = currentKartClass();
    var validation = validateCorners(corners, kartClass);

    var geometry = renderBallastLayerAvailability();
    renderBallastMarkers(geometry);

    if (validation.errors.length) {
      renderMessages(validation);
      renderResults(null, null, kartClass);
      renderCgMarkers(null, null);
      renderCornerResults(corners, null);
      renderCornerPercents(null);
      if (ballastLegendEl) ballastLegendEl.hidden = true;
      renderDiagnostics([]);
      if (ctaEl) ctaEl.hidden = true;
      return;
    }

    var appliedCorners = corners;
    if (geometry && ballasts.length) {
      appliedCorners = applyBallasts(corners, ballasts, geometry);
      ballasts.forEach(function (b) {
        validation.warnings = validation.warnings.concat(validateBallastWeight(b.weight_kg, kartClass));
      });
    }
    renderMessages(validation);
    renderCornerResults(corners, geometry && ballasts.length ? appliedCorners : null);

    var metrics = computeMetrics(appliedCorners);
    var classification = {
      front_rear: classify("front_rear", metrics.front_pct),
      left_right: classify("left_right", metrics.left_pct),
      cross_weight: classify("cross_weight", metrics.cross_pct),
    };
    renderResults(metrics, classification, kartClass);
    renderCornerPercents(metrics);
    if (geometry) renderCgMarkers(appliedCorners, geometry);
    if (ballastLegendEl) ballastLegendEl.hidden = !geometry;

    var minWeight = minWeightStatus(metrics.total_kg, kartClass);
    renderDiagnostics(diagnose(metrics, classification, minWeight, currentWeather()));

    if (ctaEl) ctaEl.hidden = false;
    trackOnce("calc_completed");
  }

  // ── Deep-link из статей Матчасти (Блок 9, ТЗ §11.3) ─────────────────
  // ?lf=..&rf=..&lr=..&rr=.. — подставить в поля и сразу посчитать.
  // Опционально &class=<id или slug>, &wb=&tf=&tr= (геометрия). Ничего
  // не сохраняется, парсинг только на клиенте.
  function applyDeepLinkParams() {
    var q;
    try { q = new URLSearchParams(window.location.search); } catch (e) { return; }
    if (!q.toString()) return;

    var touched = false;
    CORNER_KEYS.forEach(function (key) {
      var v = q.get(key);
      if (v !== null && v !== "" && !isNaN(parseWeight(v))) {
        inputs[key].value = String(round1(parseWeight(v)));
        touched = true;
      }
    });

    var cls = q.get("class");
    if (cls && classSelect) {
      for (var i = 0; i < KART_CLASSES.length; i++) {
        var kc = KART_CLASSES[i];
        if (String(kc.id) === cls || kc.slug === cls) {
          classSelect.value = String(kc.id);
          fillGeometryFromClass(kc);
          touched = true;
          break;
        }
      }
    }

    var geomMap = { wb: wheelbaseInput, tf: trackFrontInput, tr: trackRearInput };
    Object.keys(geomMap).forEach(function (param) {
      var el = geomMap[param];
      var v = q.get(param);
      if (el && v !== null && v !== "" && !isNaN(parseWeight(v))) {
        el.value = String(round1(parseWeight(v)));
        touched = true;
      }
    });

    var w = q.get("weather");
    if (w && weatherSelect && ["dry", "wet", "mixed"].indexOf(w) !== -1) {
      weatherSelect.value = w;
      touched = true;
    }

    if (touched) recalc();
  }

  CORNER_KEYS.forEach(function (key) {
    inputs[key].addEventListener("input", recalc);
  });
  if (classSelect) {
    classSelect.addEventListener("change", function () {
      fillGeometryFromClass(currentKartClass());
      recalc();
    });
  }
  if (weatherSelect) {
    weatherSelect.addEventListener("change", recalc);
  }
  if (driverWeightInput) {
    driverWeightInput.addEventListener("input", recalc);
  }
  [wheelbaseInput, trackFrontInput, trackRearInput].forEach(function (el) {
    if (el) el.addEventListener("input", recalc);
  });

  // ── Топбар: Очистить / База ──────────────────────────────────────────
  // "Очистить" — полный сброс формы. "База" — не отдельный расчётный режим
  // (формулы front/rear/cross от того, взвешен карт с пилотом или без,
  // не зависят), а быстрый переход к полю "Вес пилота" — тому самому,
  // которое отвечает за строку База/Итого выше.
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      CORNER_KEYS.forEach(function (key) {
        inputs[key].value = "";
        inputs[key].classList.remove("gl-calc-corner--error");
      });
      if (classSelect) classSelect.value = "";
      if (weatherSelect) weatherSelect.value = "";
      if (driverWeightInput) driverWeightInput.value = "";
      if (wheelbaseInput) wheelbaseInput.value = "";
      if (trackFrontInput) trackFrontInput.value = "";
      if (trackRearInput) trackRearInput.value = "";
      ballasts = [];
      hidePopup();
      renderMessages({ errors: [], warnings: [] });
      renderCornerResults({ lf: NaN, rf: NaN, lr: NaN, rr: NaN }, null);
      renderCornerPercents(null);
      renderResults(null, null, null);
      renderDiagnostics([]);
      if (ctaEl) ctaEl.hidden = true;
      if (ballastLegendEl) ballastLegendEl.hidden = true;
      var geometry = renderBallastLayerAvailability();
      renderBallastMarkers(geometry);
      renderCgMarkers(null, null);
    });
  }

  if (baseBtn) {
    baseBtn.addEventListener("click", function () {
      if (!driverWeightInput) return;
      driverWeightInput.scrollIntoView({ behavior: "smooth", block: "center" });
      driverWeightInput.focus();
    });
  }

  // Переход по ссылке "Подробнее →" в диагностике / обучающем блоке —
  // возврат трафика в Матчасть (ТЗ §10.2 diagnostic_link_clicked).
  document.addEventListener("click", function (evt) {
    var link = evt.target.closest ? evt.target.closest(
      ".gl-calc-diagnostic a, .gl-calc-lesson__link, .gl-calc-landing__reading-list a"
    ) : null;
    if (link) track("diagnostic_link_clicked", { url: link.getAttribute("href") });
  });

  // ── Инфо-модалка («Почему не 50/50», точность расчёта) ──────────────
  // Контент лежит в <template> (не рендерится в DOM сам по себе) — клик по
  // кнопке-иконке клонирует его содержимое в общую модалку. Один компонент
  // на оба триггера, а не два разных попапа.
  var infoModal = document.getElementById("glCalcInfoModal");
  var infoModalBody = document.getElementById("glCalcInfoModalBody");
  var infoModalClose = document.getElementById("glCalcInfoModalClose");
  var infoModalBackdrop = document.getElementById("glCalcInfoModalBackdrop");

  function openInfoModal(templateId) {
    var tpl = document.getElementById(templateId);
    if (!tpl || !infoModal || !infoModalBody) return;
    infoModalBody.innerHTML = "";
    infoModalBody.appendChild(tpl.content.cloneNode(true));
    infoModal.hidden = false;
  }

  function closeInfoModal() {
    if (infoModal) infoModal.hidden = true;
  }

  if (infoModalClose) infoModalClose.addEventListener("click", closeInfoModal);
  if (infoModalBackdrop) infoModalBackdrop.addEventListener("click", closeInfoModal);
  document.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape") closeInfoModal();
  });

  var why4357Btn = document.getElementById("glCalcWhy4357Btn");
  if (why4357Btn) {
    why4357Btn.addEventListener("click", function () { openInfoModal("glCalcInfoWhy4357"); });
  }

  var ballastDisclaimerBtn = document.getElementById("glCalcBallastDisclaimerBtn");
  if (ballastDisclaimerBtn) {
    ballastDisclaimerBtn.addEventListener("click", function () { openInfoModal("glCalcInfoBallastDisclaimer"); });
  }

  // ── API для сохранения (Блок 3, balance-setup-editor.js) ────────────
  // Снимок текущего состояния калькулятора / восстановление снимка.
  // getState() отдаёт сырые значения полей (строки) — та же форма, что
  // отправляется на сервер (setup_save парсит их теми же validate_corners/
  // Decimal-правилами, что и здесь). loadState() выставляет их обратно и
  // пересчитывает — используется и для "загрузить сетап на редактирование"
  // (следующие этапы плана), и для восстановления анонимного ввода после
  // ухода на OAuth и возврата (см. balance-setup-editor.js — там же TTL).
  window.GripBalanceCalc = {
    getState: function () {
      return {
        corners: {
          lf: inputs.lf.value,
          rf: inputs.rf.value,
          lr: inputs.lr.value,
          rr: inputs.rr.value,
        },
        class_id: classSelect ? classSelect.value : "",
        weather: weatherSelect ? weatherSelect.value : "",
        driver_weight: driverWeightInput ? driverWeightInput.value : "",
        wheelbase_mm: wheelbaseInput ? wheelbaseInput.value : "",
        track_front_mm: trackFrontInput ? trackFrontInput.value : "",
        track_rear_mm: trackRearInput ? trackRearInput.value : "",
        ballasts: ballasts.map(function (b) {
          return { weight_kg: b.weight_kg, pos_x_mm: b.pos_x_mm, pos_y_mm: b.pos_y_mm, label: b.label };
        }),
      };
    },
    loadState: function (state) {
      if (!state) return;
      if (state.corners) {
        CORNER_KEYS.forEach(function (key) {
          var v = state.corners[key];
          if (v !== undefined && v !== null && v !== "") inputs[key].value = v;
        });
      }
      if (state.class_id && classSelect) classSelect.value = state.class_id;
      if (state.weather && weatherSelect) weatherSelect.value = state.weather;
      if (state.driver_weight && driverWeightInput) driverWeightInput.value = state.driver_weight;
      if (state.wheelbase_mm && wheelbaseInput) wheelbaseInput.value = state.wheelbase_mm;
      if (state.track_front_mm && trackFrontInput) trackFrontInput.value = state.track_front_mm;
      if (state.track_rear_mm && trackRearInput) trackRearInput.value = state.track_rear_mm;
      if (Array.isArray(state.ballasts)) {
        ballasts = state.ballasts.map(function (b) {
          return {
            id: nextBallastId++,
            weight_kg: round1(parseWeight(b.weight_kg)),
            pos_x_mm: parseWeight(b.pos_x_mm),
            pos_y_mm: parseWeight(b.pos_y_mm),
            label: b.label || "",
          };
        }).filter(function (b) {
          return !isNaN(b.weight_kg) && !isNaN(b.pos_x_mm) && !isNaN(b.pos_y_mm);
        });
      }
      recalc();
    },
  };

  renderBallastLayerAvailability();
  applyDeepLinkParams();

  // Намеренно не считаем сразу при загрузке — четыре сообщения "не
  // заполнено" в первую же секунду выглядели бы как нытьё, а не подсказка.
  // Расчёт стартует с первого реального ввода.
})();
