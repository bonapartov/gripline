"""Идеальный круг (сумма лучших секторов) не бывает медленнее лучшего круга и не равен ему."""
from website.models import RaceResult


def _r(**kw):
    return RaceResult(**kw)


def test_ideal_mixes_best_sectors_across_sessions():
    r = _r(qual_best_lap_ms=63500, qual_s1_ms=18000, qual_s2_ms=25500, qual_s3_ms=20000,
           pre_final_best_lap_ms=63600, pre_final_s1_ms=18100, pre_final_s2_ms=25400, pre_final_s3_ms=20100)
    assert r.ideal_lap_all_ms == 18000 + 25400 + 20000
    assert r.ideal_lap_session is None


def test_ideal_hidden_when_sectors_only_of_best_lap():
    # протокол даёт секторы лучшего круга: сумма = круг, это не идеальный
    r = _r(qual_best_lap_ms=63279, qual_s1_ms=17900, qual_s2_ms=25364, qual_s3_ms=20015)
    assert r.ideal_lap_all_ms is None
    assert r.ideal_lap_session is None


def test_ideal_hidden_when_best_lap_session_has_no_sectors():
    # финал быстрее, секторов у финала нет: «идеальный» из квалификации медленнее лучшего круга
    r = _r(best_lap_ms=64440, qual_best_lap_ms=64750, qual_s1_ms=18464, qual_s2_ms=25895, qual_s3_ms=20391)
    assert r.best_lap_all_ms == 64440
    assert r.ideal_lap_all_ms is None
