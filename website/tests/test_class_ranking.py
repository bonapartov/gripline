"""Место пилота на его странице совпадает с таблицей /top/drivers/ (18.10.2026).

Раньше страница пилота считала место по всем пилотам класса, а таблица — без давно
не выступавших: другая медиана для сглаживания и лишние пилоты выше → №4 в таблице,
№5 на странице.
"""
from datetime import date, timedelta

import pytest

from website.models import Driver, RaceClass
from website.views import _class_ranking_entries

pytestmark = pytest.mark.django_db


def _driver(name, score, starts, days_ago, klass):
    last = (date.today() - timedelta(days=days_ago)).isoformat()
    return Driver.objects.create(
        first_name=name, last_name=name, slug=name.lower(),
        rating_by_class={str(klass.id): {'score': score, 'starts': starts, 'last_race_date': last}})


def test_inactive_drivers_do_not_shift_places():
    klass = RaceClass.objects.create(name='RM Mini')
    _driver('Лидер', 3.0, 15, 10, klass)
    best_few = _driver('Новичок', 3.0, 7, 10, klass)
    _driver('Середняк', 1.8, 14, 10, klass)
    _driver('Слабый', 0.5, 14, 10, klass)
    for i in range(5):  # давно не выступали: в таблице их нет
        _driver(f'Ушедший{i}', -1.0, 14, 800, klass)

    entries = _class_ranking_entries(klass.id, Driver.objects.all(), keep_driver_id=best_few.id)
    assert all(not e['inactive'] for e in entries)
    assert len(entries) == 4
    assert [e['full_name'].split()[0] for e in entries] == ['Лидер', 'Новичок', 'Середняк', 'Слабый']


def test_inactive_driver_gets_virtual_place_without_moving_others():
    klass = RaceClass.objects.create(name='RM Micro')
    _driver('Первый', 3.0, 15, 10, klass)
    _driver('Второй', 1.0, 15, 10, klass)
    gone = _driver('Ушедший', 2.0, 15, 800, klass)

    entries = _class_ranking_entries(klass.id, Driver.objects.all(), keep_driver_id=gone.id)
    by_name = {e['full_name'].split()[0]: e for e in entries}
    assert by_name['Ушедший']['inactive'] is True
    assert by_name['Ушедший']['rank'] == 2
    assert by_name['Первый']['rank'] == 1 and by_name['Второй']['rank'] == 2
    assert by_name['Ушедший']['total'] == 2

    # без keep_driver_id неактивного нет вовсе
    assert 'Ушедший' not in {e['full_name'].split()[0] for e in _class_ranking_entries(klass.id, Driver.objects.all())}


def test_no_absence_penalty_before_first_start_in_class():
    """Пилот перешёл в класс позже — этапы класса до его дебюта не считаются пропусками."""
    import pandas as pd
    from types import SimpleNamespace
    from website.management.commands.update_ratings import Command

    settings = SimpleNamespace(inactive_threshold_days=365, lambda_active=0.8, lambda_inactive=2.0)
    d = lambda s: pd.Timestamp(s)
    df = pd.DataFrame([
        # этап 1 — новичка ещё нет в классе
        {'group_id': 1, 'driver_id': 10, 'position': 1, 'date': d('2026-03-01')},
        {'group_id': 1, 'driver_id': 11, 'position': 2, 'date': d('2026-03-01')},
        # этап 2 — дебют новичка (20)
        {'group_id': 2, 'driver_id': 20, 'position': 1, 'date': d('2026-05-01')},
        {'group_id': 2, 'driver_id': 10, 'position': 2, 'date': d('2026-05-01')},
        {'group_id': 2, 'driver_id': 11, 'position': 3, 'date': d('2026-05-01')},
        # этап 3 — новичок пропустил
        {'group_id': 3, 'driver_id': 10, 'position': 1, 'date': d('2026-07-01')},
        {'group_id': 3, 'driver_id': 11, 'position': 2, 'date': d('2026-07-01')},
    ])
    comps = Command()._create_class_comparisons(df, 'driver', settings)
    losses = comps[comps['loser_id'] == 20]
    assert set(losses['group_id']) == {3}, 'до дебюта (этап 1) штрафа нет, после (этап 3) — есть'


def test_few_starts_not_in_table_but_shown_on_own_page():
    """Меньше min_starts_display стартов — нет в таблице, на своей странице «мало стартов»."""
    klass = RaceClass.objects.create(name='RM Junior')
    _driver('Опытный', 1.0, 10, 10, klass)
    _driver('Средний', 0.5, 8, 10, klass)
    rookie = _driver('Новичок', 5.0, 1, 10, klass)

    table = _class_ranking_entries(klass.id, Driver.objects.all())
    assert [e['full_name'].split()[0] for e in table] == ['Опытный', 'Средний']

    own = _class_ranking_entries(klass.id, Driver.objects.all(), keep_driver_id=rookie.id)
    me = next(e for e in own if e['driver_id'] == rookie.id)
    assert me['inactive'] is True and me['out_reason'] == 'few_starts'
    assert me['total'] == 2
