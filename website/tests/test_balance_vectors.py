"""Контрольные примеры развесовки — общие для трёх копий формул: Python (здесь), JS (balance-calculator.js)
и Dart (приложение GripLine SetupKart, test/fixtures/balance_vectors.json — копия этого файла). При правке
формулы менять все три и этот файл."""
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from website.models import BalanceThreshold
from website.services import balance_calc as bc

VECTORS = json.loads((Path(__file__).parent / 'fixtures' / 'balance_vectors.json').read_text())
THRESHOLDS = {k: BalanceThreshold(metric=k, **{f: Decimal(str(v)) for f, v in t.items()})
              for k, t in VECTORS['thresholds'].items()}
RULES = {c: SimpleNamespace(text=c + ('|{shortfall_kg}' if c == 'under_min_weight' else ''), article=None)
         for c in ('front_high', 'front_low', 'cross_diagonal', 'cross_mechanical', 'lr_asymmetry', 'wet_weather',
                   'under_min_weight')}


@pytest.mark.parametrize('case', VECTORS['cases'], ids=[c['name'] for c in VECTORS['cases']])
def test_balance_vector(case):
    corners = [Decimal(str(case['corners'][k])) for k in ('lf', 'rf', 'lr', 'rr')]
    metrics = bc.compute_metrics(*corners)
    assert {k: float(v) for k, v in metrics.items()} == case['metrics']
    classification = bc.classify_all(metrics, thresholds=THRESHOLDS)
    assert classification == case['classification']
    kart_class = SimpleNamespace(min_weight_kg=Decimal(str(case['min_weight_kg']))) if case['min_weight_kg'] else None
    min_weight = bc.min_weight_status(metrics['total_kg'], kart_class)
    assert (float(min_weight['margin_kg']) if min_weight else None) == case['margin_kg']
    diagnosis = bc.diagnose(metrics, classification, min_weight, thresholds=THRESHOLDS, weather=case['weather'],
                            rules=RULES)
    assert [d['text'] for d in diagnosis] == case['diagnosis']
