"""Regression tests for the agreed CSV -> result -> rating -> record rules."""
import csv
import datetime as dt
import io

import pandas as pd
import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone
from wagtail.models import Locale, Page

from analytics.core.data_loader import DataLoader
from analytics.core.results import ranked_rows
from website import import_utils as imp
from website.management.commands.update_ratings import Command
from website.models import (AnalyticsSettings, Driver, EventOccurrence, EventPage,
                            RaceClass, RaceClassResultGroup, RaceResult, Track)
from website.services import track_stats
from website.setupkart.records import records_by_track
from website.views import _compute_all_track_records


@pytest.fixture
def world(db):
    Locale.objects.get_or_create(language_code='ru')
    Locale.objects.get_or_create(language_code='en')
    root = Page.get_first_root_node() or Page.add_root(title='Synthetic root', slug='synthetic-root')
    track = Track.objects.create(name='Synthetic track', slug='synthetic-track', live=True)
    klass = RaceClass.objects.create(name='Synthetic class')
    return root, track, klass


def group(world, suffix='one', live=True, start=None, end=None):
    root, track, klass = world
    start = start or timezone.make_aware(dt.datetime(2026, 6, 1, 9))
    end = end or timezone.make_aware(dt.datetime(2026, 6, 1, 18))
    page = root.add_child(instance=EventPage(title='Synthetic event ' + suffix,
        slug='synthetic-' + suffix, track=track, live=live, first_published_at=start))
    EventOccurrence.objects.create(event=page, start=start, end=end)
    return RaceClassResultGroup.objects.create(page=page, race_class=klass)


def driver(n):
    return Driver.objects.create(first_name='Synthetic', last_name=f'Pilot{n}', slug=f'synthetic-{n}')


def request(data, session):
    req = RequestFactory().post('/diagnostic/', data)
    req.session = session
    req._messages = FallbackStorage(req)
    return req


def csv_pipeline(g, session_type, rows, monkeypatch):
    """Exercise upload parser and actual preview form/confirm, mock navigation only."""
    monkeypatch.setattr(imp, 'redirect', lambda *a, **kw: HttpResponse(status=302))
    captured = {}
    def render(req, template, context):
        captured.clear()
        captured.update(context)
        return HttpResponse('preview')
    monkeypatch.setattr(imp, 'render', render)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    session = {}
    upload = SimpleUploadedFile('synthetic.csv', buffer.getvalue().encode(), content_type='text/csv')
    response = imp.import_results(request({'upload': '1', 'session_type': session_type,
        'race_class_group': str(g.pk), 'csv_file': upload}, session), page_id=g.page_id)
    assert response.status_code == 302
    req = RequestFactory().get('/preview/')
    req.session = session
    req._messages = FallbackStorage(req)
    imp.import_preview(req)
    post = {}
    for i, row in enumerate(captured['rows']):
        post[f'driver_{i}'] = str(row['selected_driver_id'])
        for key in imp.HIDDEN_FIELDS:
            if key in row:
                post[f'{key}_{i}'] = row.get(key) or ''
    response = imp.import_preview(request(post, session))
    if captured.get('import_errors'):
        assert not session.get('import_selections')
        return captured
    assert response.status_code == 302 and session.get('import_selections'), captured
    req = request({}, session)
    assert imp.import_confirm(req).status_code == 302
    assert not any('Ошибка:' in str(m) for m in req._messages)
    return captured


def row(pilot, position='1', **kwargs):
    return {'first_name': pilot.first_name, 'last_name': pilot.last_name,
            'position': position, **kwargs}


@pytest.mark.parametrize('mode,field', imp.STATUS_FIELDS.items())
@pytest.mark.parametrize('status', ['DQ', 'DNS', 'DNF'])
@pytest.mark.parametrize('source', ['status', 'explicit', 'position'])
def test_status_survives_csv_preview_and_database(world, monkeypatch, mode, field, status, source):
    g, p = group(world), driver(1)
    data = row(p, points='7')
    if source == 'position':
        data['position'] = status
    else:
        data['status' if source == 'status' else field] = status
    csv_pipeline(g, mode, [data], monkeypatch)
    r = RaceResult.objects.get(group=g, driver=p)
    assert getattr(r, field) == status
    if mode == 'protocol':
        assert r.points == 7
    if mode in ('protocol', 'final'):
        assert r.position == (0 if source == 'position' else 1)


def test_status_absent_preserves_manual_and_explicit_empty_clears(world, monkeypatch):
    g, p = group(world), driver(1)
    RaceResult.objects.create(group=g, driver=p, position=1, final_status='DQ')
    csv_pipeline(g, 'final', [row(p)], monkeypatch)
    assert RaceResult.objects.get(group=g, driver=p).final_status == 'DQ'
    csv_pipeline(g, 'final', [row(p, status='')], monkeypatch)
    assert RaceResult.objects.get(group=g, driver=p).final_status == ''


def test_preview_html_carries_status_and_presence_marker(world):
    g, p = group(world), driver(1)
    req = RequestFactory().get('/preview/')
    req.session = {'import_rows': [row(p, final_status='DQ')],
                   'import_session_type': 'final', 'import_group_id': g.pk}
    req._messages = FallbackStorage(req)
    html = imp.import_preview(req).content.decode()
    assert 'name="status_0" value="DQ"' in html
    assert 'name="status_supplied_0" value="1"' in html


@pytest.mark.parametrize('bad', [
    {'position': 'DSQ'}, {'position': '-1'}, {'position': '1.5'},
    {'status': 'RETIRED'}, {'position': 'DQ', 'status': 'DNS'},
    {'points': 'NaN'}, {'best_lap': 'unknown'}, {'start_position': '-2'},
    {'best_lap': 'Infinity'}, {'points': '1e9999'},
])
def test_bad_csv_rejected_before_any_result_write(world, monkeypatch, bad):
    g, a, b = group(world), driver(1), driver(2)
    result = csv_pipeline(g, 'final', [row(a), {**row(b), **bad}], monkeypatch)
    assert result['import_errors']
    assert not RaceResult.objects.exists()


def test_tampered_confirm_batch_validated_before_creating_driver(world, monkeypatch):
    g = group(world)
    monkeypatch.setattr(imp, 'redirect', lambda *a, **kw: HttpResponse(status=302))
    entries = [dict(first_name='Synthetic', last_name='New', position='1', selected_driver_id='new'),
               dict(first_name='Synthetic', last_name='Bad', position='garbage', selected_driver_id='new')]
    req = request({}, {'import_selections': entries, 'import_session_type': 'final',
                        'import_group_id': g.pk})
    assert imp.import_confirm(req).status_code == 302
    assert not Driver.objects.exists() and not RaceResult.objects.exists()


@pytest.mark.parametrize('position,status', [(0, ''), (1, 'DNS'), (1, 'DQ'), (0, 'DNF')])
def test_excluded_entrant_gets_neither_comparisons_nor_absence_losses(position, status):
    rows = []
    for gid, date in [(1, '2026-01-01'), (2, '2026-02-01'), (3, '2026-03-01')]:
        for did in (1, 2, 3):
            if gid == 3 and did == 1:
                continue  # a genuine absence remains a virtual loss
            rows.append({'group_id': gid, 'driver_id': did, 'position': did,
                         'date': pd.Timestamp(date), 'final_status': ''})
    rows[3].update(position=position, final_status=status)
    df = pd.DataFrame(rows)
    s = type('S', (), {'lambda_active': 0})()
    pairs = Command()._create_class_comparisons(df, 'driver', s)
    excluded_group = pairs[pairs.group_id == 2]
    assert not (excluded_group.entity_1_id.eq(1) | excluded_group.entity_2_id.eq(1)).any()
    assert set(pairs[pairs.loser_id == 1].group_id) == {3}


def test_unclassified_debut_does_not_start_absence_penalties():
    df = pd.DataFrame([
        {'group_id': gid, 'driver_id': did, 'position': pos, 'date': pd.Timestamp(date)}
        for gid, date, values in [(1, '2026-01-01', [(1, 0), (2, 1), (3, 2)]),
                                  (2, '2026-02-01', [(2, 1), (3, 2)]),
                                  (3, '2026-03-01', [(1, 1), (2, 2), (3, 3)])]
        for did, pos in values])
    pairs = Command()._create_class_comparisons(df, 'driver', type('S', (), {'lambda_active': 0})())
    assert not ((pairs.group_id < 3) & (pairs.entity_1_id.eq(1) | pairs.entity_2_id.eq(1))).any()


def test_dnf_with_position_is_classified_and_qual_dq_does_not_remove_final():
    df = pd.DataFrame([
        {'position': 1, 'final_status': 'DNF', 'qual_status': 'DQ'},
        {'position': 2, 'final_status': '', 'pre_final_status': 'DQ'},
        {'position': 0, 'final_status': 'DNF'},
    ])
    assert list(ranked_rows(df).position) == [1, 2]


@pytest.mark.parametrize('groups,pilots,min_pairs,computed', [
    (1, 5, 10, False), (2, 5, 10, False), (3, 3, 10, True), (3, 2, 10, False),
])
def test_three_distinct_races_plus_comparison_threshold(world, groups, pilots, min_pairs, computed):
    racers = [driver(i) for i in range(pilots)]
    for j in range(groups):
        g = group(world, str(j))
        for i, p in enumerate(racers):
            RaceResult.objects.create(group=g, driver=p, position=i + 1)
    loader = DataLoader()
    loader.load_all_data()
    s = AnalyticsSettings.get()
    assert s.min_races_per_class == 3
    s.min_comparisons, s.lambda_active = min_pairs, 0
    scores = Command(stdout=io.StringIO())._update_driver_bt_ratings(loader, s)
    assert bool(scores) == computed
    assert sum(bool(d.rating_by_class) for d in Driver.objects.all()) == (pilots if computed else 0)


def test_recalculation_removes_stale_class_rating_for_excluded_driver(world):
    a, b, c = [driver(i) for i in range(3)]
    klass = world[2]
    a.rating_by_class = {str(klass.pk): {'score': 99, 'starts': 10}}
    a.save()
    for j in range(3):
        g = group(world, str(j))
        for i, p in enumerate((a, b, c)):
            RaceResult.objects.create(group=g, driver=p, position=i + 1,
                                      final_status='DQ' if p == a else '')
    loader = DataLoader()
    loader.load_all_data()
    s = AnalyticsSettings.get()
    s.min_comparisons = 2
    Command(stdout=io.StringIO())._update_driver_bt_ratings(loader, s)
    a.refresh_from_db()
    assert a.rating_by_class == {}


def test_threshold_change_drops_previous_class_snapshot(world):
    g, p = group(world), driver(1)
    klass = world[2]
    RaceResult.objects.create(group=g, driver=p, position=1)
    p.rating_by_class = {str(klass.pk): {'score': 99, 'starts': 10}}
    p.save()
    loader = DataLoader()
    loader.load_all_data()
    Command(stdout=io.StringIO())._update_driver_bt_ratings(loader, AnalyticsSettings.get())
    p.refresh_from_db()
    assert p.rating_by_class == {}


def test_threshold_migration_updates_existing_setting_only_in_test_db(world):
    import importlib
    from django.apps import apps
    from django.db import connection
    s = AnalyticsSettings.get()
    s.min_races_per_class = 5
    s.save()
    migration = importlib.import_module('website.migrations.0110_analytics_min_class_races')
    with connection.schema_editor() as editor:
        migration.set_three_races(apps, editor)
    s.refresh_from_db()
    assert s.min_races_per_class == 3


@pytest.mark.parametrize('status,expected', [('DQ', 55000), ('DNS', 55000), ('DNF', 50000), ('', 50000)])
def test_record_page_cache_and_app_agree_on_session_rules(world, status, expected):
    g = group(world)
    _, track, klass = world
    a, b = driver(1), driver(2)
    RaceResult.objects.create(group=g, driver=a, position=1, best_lap_ms=50000,
                              final_status=status, qual_best_lap_ms=60000)
    RaceResult.objects.create(group=g, driver=b, position=2, best_lap_ms=55000)
    hidden = group(world, 'hidden', live=False)
    RaceResult.objects.create(group=hidden, driver=a, position=1, best_lap_ms=40000)
    shown = track_stats.best_lap(track_stats.load_rows(track))
    track.records_cache = _compute_all_track_records()[track.pk]
    track.save(update_fields=['records_cache'])
    track.refresh_from_db()
    assert shown['ms'] == track.records_cache[str(klass.pk)]['lap_ms'] == expected
    assert records_by_track([track])[track.pk][0]['lap_ms'] == expected
    loader = DataLoader()
    assert len(loader.load_all_data()) == 2


def test_record_and_rating_dates_use_latest_end_in_site_timezone(world):
    start = timezone.make_aware(dt.datetime(2025, 12, 31, 9))
    end = timezone.make_aware(dt.datetime(2026, 1, 1, 18))
    g = group(world, start=start, end=end)
    _, track, klass = world
    EventOccurrence.objects.create(event=g.page, start=start, end=end - dt.timedelta(hours=2))
    RaceResult.objects.create(group=g, driver=driver(1), position=1, best_lap_ms=60000)
    shown = track_stats.best_lap(track_stats.load_rows(track))
    rec = _compute_all_track_records()[track.pk][str(klass.pk)]
    loader = DataLoader()
    assert loader.load_all_data().iloc[0]['date'].date() == shown['date'] == end.date()
    assert rec['record_year'] == 2026 and rec['record_date'] == '2026-01-01'


def test_negative_lap_is_not_a_record_in_either_source(world):
    g = group(world)
    _, track, klass = world
    RaceResult.objects.create(group=g, driver=driver(1), position=1,
                              best_lap_ms=-1, qual_best_lap_ms=60000)
    assert track_stats.best_lap(track_stats.load_rows(track))['ms'] == 60000
    assert _compute_all_track_records()[track.pk][str(klass.pk)]['lap_ms'] == 60000


def test_undated_result_is_excluded_from_both_record_sources(world):
    root, track, klass = world
    page = root.add_child(instance=EventPage(title='Undated synthetic', slug='undated',
                                           track=track, live=True))
    g = RaceClassResultGroup.objects.create(page=page, race_class=klass)
    RaceResult.objects.create(group=g, driver=driver(1), position=1, best_lap_ms=60000)
    assert track_stats.load_rows(track) == []
    assert _compute_all_track_records() == {}


def test_disqualified_sectors_do_not_supply_ideal_lap():
    r = RaceResult(qual_status='DQ', qual_best_lap_ms=45000,
                   qual_s1_ms=10000, qual_s2_ms=10000, qual_s3_ms=10000,
                   best_lap_ms=60000, best_s1_ms=20000, best_s2_ms=19000, best_s3_ms=20000)
    assert r.best_lap_all_ms == 60000 and r.best_lap_session == 'final'
    assert r.ideal_lap_all_ms == 59000 and r.ideal_lap_session == 'final'


def test_combined_csv_dq_never_beats_classified_result_or_supplies_record(world, monkeypatch):
    g, a, b = group(world), driver(1), driver(2)
    csv_pipeline(g, 'combined', [
        row(a, session_type='protocol', position='DQ', points='7'),
        row(a, session_type='final', position='DQ', best_lap='50.000'),
        row(b, session_type='protocol', position='1', points='25'),
        row(b, session_type='final', position='1', best_lap='55.000'),
    ], monkeypatch)
    r = RaceResult.objects.get(group=g, driver=a)
    assert r.final_status == 'DQ' and r.position == 0 and r.points == 7
    loader = DataLoader()
    loader.load_all_data()
    assert list(ranked_rows(loader.df_races).driver_id) == [b.pk]
    s = AnalyticsSettings.get()
    assert Command()._create_class_comparisons(loader.df_races, 'driver', s).empty
    _, track, klass = world
    assert track_stats.best_lap(track_stats.load_rows(track))['ms'] == 55000
    assert _compute_all_track_records()[track.pk][str(klass.pk)]['lap_ms'] == 55000
