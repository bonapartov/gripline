// Прогоняет формулы balance-calculator.js на контрольных примерах balance_vectors.json и печатает
// результаты JSON-ом; сравнивает их с ожидаемыми website/tests/test_balance_vectors_js.py.
// Запуск: node balance_vectors_runner.cjs <balance-calculator.js> <balance_vectors.json>
"use strict";
const fs = require("fs");
const vm = require("vm");

const [calcPath, vectorsPath] = process.argv.slice(2);
const vectors = JSON.parse(fs.readFileSync(vectorsPath, "utf8"));

// Те же тексты правил, что в test_balance_vectors.py: имя условия (+ подстановка недобора).
const rules = {};
["front_high", "front_low", "cross_diagonal", "cross_mechanical", "lr_asymmetry", "wet_weather", "under_min_weight"]
  .forEach((c) => { rules[c] = { text: c + (c === "under_min_weight" ? "|{shortfall_kg}" : "") }; });

const json = { balanceKartClasses: [], balanceThresholds: vectors.thresholds, balanceDiagnosticRules: rules };
const document = {
  getElementById: (id) => (id in json ? { textContent: JSON.stringify(json[id]) } : null),
  querySelector: () => null,
  querySelectorAll: () => [],
};
const sandboxModule = { exports: {} };
vm.runInNewContext(fs.readFileSync(calcPath, "utf8"), { document, module: sandboxModule, window: {}, console });
const m = sandboxModule.exports;

const cases = vectors.cases.map((c) => {
  const metrics = m.computeMetrics(c.corners);
  delete metrics.corner_pct; // презентационное поле, только в JS
  const classification = {
    front_rear: m.classify("front_rear", metrics.front_pct),
    left_right: m.classify("left_right", metrics.left_pct),
    cross_weight: m.classify("cross_weight", metrics.cross_pct),
  };
  const minWeight = m.minWeightStatus(metrics.total_kg, c.min_weight_kg ? { min_weight_kg: c.min_weight_kg } : null);
  const diagnosis = m.diagnose(metrics, classification, minWeight, c.weather).map((d) => d.text);
  return { name: c.name, metrics, classification, margin_kg: minWeight ? minWeight.margin_kg : null, diagnosis };
});

const ballastCases = vectors.ballast_cases.map((c) => ({
  name: c.name,
  applied: m.applyBallasts(c.corners, c.ballasts, {
    wheelbaseMm: c.geometry.wheelbase_mm,
    trackFrontMm: c.geometry.track_front_mm,
    trackRearMm: c.geometry.track_rear_mm,
  }),
}));

process.stdout.write(JSON.stringify({ cases, ballast_cases: ballastCases }));
