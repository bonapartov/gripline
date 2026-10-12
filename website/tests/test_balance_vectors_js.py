"""Паритет JS-копии формул развесовки (balance-calculator.js) с контрольными примерами balance_vectors.json —
тех же, на которых проверяются Python (test_balance_vectors.py) и приложение. Без Node тест пропускается."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CALC_JS = ROOT / 'website' / 'static' / 'website' / 'js' / 'balance-calculator.js'
RUNNER = Path(__file__).parent / 'js' / 'balance_vectors_runner.cjs'
VECTORS_PATH = Path(__file__).parent / 'fixtures' / 'balance_vectors.json'
VECTORS = json.loads(VECTORS_PATH.read_text())

pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='нет Node.js')


@pytest.fixture(scope='module')
def js_results():
    out = subprocess.run(
        ['node', str(RUNNER), str(CALC_JS), str(VECTORS_PATH)],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout
    return json.loads(out)


@pytest.mark.parametrize('i', range(len(VECTORS['cases'])), ids=[c['name'] for c in VECTORS['cases']])
def test_js_balance_vector(js_results, i):
    case, got = VECTORS['cases'][i], js_results['cases'][i]
    assert got['metrics'] == case['metrics']
    assert got['classification'] == case['classification']
    assert got['margin_kg'] == case['margin_kg']
    assert got['diagnosis'] == case['diagnosis']


@pytest.mark.parametrize('i', range(len(VECTORS['ballast_cases'])),
                         ids=[c['name'] for c in VECTORS['ballast_cases']])
def test_js_ballast_vector(js_results, i):
    assert js_results['ballast_cases'][i]['applied'] == VECTORS['ballast_cases'][i]['applied']
