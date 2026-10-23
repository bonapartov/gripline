"""Страница трассы: расчёты по классам (рекорды, секторы, медиана, лидеры, история), вьюхи и редактор."""
import datetime
import json

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.utils import timezone
from wagtail.coreutils import get_supported_content_language_variant
from wagtail.models import Locale, Page, Site

from website.models import Driver, EventOccurrence, EventPage, RaceClass, RaceClassResultGroup, RaceResult, Track
from website.services import track_stats as st
from website.tests.test_track_scheme import scheme as make_scheme

D1, D2 = datetime.date(2025, 6, 1), datetime.date(2026, 6, 14)


def row(driver, event, date, position=1, cls=1, qual=None, pre=None, final=None):
    """qual/pre/final — (круг, s1, s2, s3) в мс, None — сессии не было."""
    sessions = {}
    for key, v in (('qual', qual), ('pre_final', pre), ('final', final)):
        if v:
            sessions[key] = {'lap': v[0], 'sec': list(v[1:])}
    return {'class_id': cls, 'class_name': f'Класс {cls}', 'class_order': (cls, ''),
            'driver_id': driver, 'driver_name': f'Пилот {driver}', 'driver_url': f'/drivers/p{driver}/',
            'event_id': event, 'event_url': f'/e{event}/', 'date': date, 'position': position,
            'sessions': sessions}


ROWS = [
    # этап 1 (2025)
    row(1, 1, D1, 1, qual=(64000, 22000, 20100, 21900), final=(63900, 21950, 20200, 21750)),
    row(2, 1, D1, 2, qual=(64300, 22100, 20000, 22200)),
    # этап 2 (2026) — последний: по нему медиана
    row(1, 2, D2, 2, qual=(63700, 21900, 20050, 21700)),
    row(2, 2, D2, 1, final=(63500, 21800, 20150, 21600), pre=(63800, 21850, 19950, 21900)),
    row(3, 2, D2, 3, qual=(64500, 22300, 20400, 22000)),
]


def test_record_is_best_lap_any_session_with_holder():
    rec = st.best_lap(ROWS)
    assert (rec['ms'], rec['driver_name'], rec['session'], rec['date']) == (63500, 'Пилот 2', 'final', D2)
    assert rec['session_label'] == 'финал' and rec['event_url'] == '/e2/'


def test_equal_lap_keeps_earlier_holder():
    rows = [row(1, 2, D2, qual=(63000, 1, 1, 1)), row(2, 1, D1, qual=(63000, 1, 1, 1))]
    assert st.best_lap(rows)['driver_name'] == 'Пилот 2'


def test_sectors_ideal_gap_and_shares():
    c = st.class_data(ROWS, [2025, 2026])
    assert c['has_sectors']
    assert [s['ms'] for s in c['sectors']] == [21800, 19950, 21600]
    assert c['sectors'][1]['session'] == 'pre_final'
    assert c['ideal_ms'] == 21800 + 19950 + 21600
    assert c['gap_ms'] == 63500 - c['ideal_ms']
    assert c['sectors'][0]['share'] == f"{21800 / c['ideal_ms'] * 100:.1f}"


def test_median_is_from_last_stage_best_per_driver():
    # последний этап — event 2: S1 у пилотов 21900, min(21800, 21850)=21800, 22300 → медиана 21900
    assert st.field_medians(ROWS) == [21900, 20050, 21700]


def test_median_skips_last_stage_without_sectors():
    rows = ROWS + [row(1, 3, datetime.date(2026, 9, 1), qual=(63000, None, None, None))]
    assert st.field_medians(rows) == [21900, 20050, 21700]


def test_class_without_full_sectors():
    rows = [row(1, 1, D1, qual=(64000, 22000, None, None))]
    c = st.class_data(rows, [2025])
    assert not c['has_sectors'] and c['sectors'] == [] and c['ideal_ms'] is None
    assert c['record']['ms'] == 64000


def test_leaders_sorted_by_wins_podiums_starts():
    lead = st.leaders(ROWS)
    assert [(x['driver_name'], x['starts'], x['wins'], x['podiums']) for x in lead] == [
        ('Пилот 1', 2, 1, 2), ('Пилот 2', 2, 1, 2), ('Пилот 3', 1, 0, 1)]


def test_position_zero_is_start_but_not_podium():
    lead = st.leaders([row(1, 1, D1, position=0)])
    assert (lead[0]['starts'], lead[0]['wins'], lead[0]['podiums']) == (1, 0, 0)


def test_years_and_record_history():
    c = st.class_data(ROWS, [2024, 2025, 2026])
    assert [(y['year'], y['races'], y['drivers']) for y in c['years']] == [(2024, 0, 0), (2025, 1, 2), (2026, 1, 3)]
    hist = c['history']
    assert [(h['year'], h['ms'], h['delta_text']) for h in hist] == [(2026, 63500, '−0.400'), (2025, 63900, '—')]


def test_slower_year_shows_plus():
    rows = [row(1, 1, D1, qual=(63000, 1, 1, 1)), row(1, 2, D2, qual=(63250, 1, 1, 1))]
    assert st.record_history(rows)[0]['delta_text'] == '+0.250'


def test_default_class_is_most_started_and_absolute_record():
    rows = ROWS + [row(9, 5, D2, cls=2, qual=(61000, 1, 1, 1))]
    classes = st.build_track_classes(rows)
    assert [c['id'] for c in classes] == [1, 2]
    assert st.default_class(classes)['id'] == 1
    assert st.absolute_record(classes) == {'ms': 61000, 'class_name': 'Класс 2'}


# ── БД, вьюхи, редактор ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


@pytest.fixture
def track(db):
    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
    root = Page.add_root(title='Root', slug='root')
    Site.objects.create(hostname='testserver', root_page=root, is_default_site=True)
    track = Track.objects.create(name='Картодром «Аргамак»', slug='argamak', city='Казань', live=True,
                                 latitude=55.8, longitude=49.1, length_m='1248.40', app_direction='ccw')
    kz = RaceClass.objects.create(name='KZ2', sort_order=10)
    mini = RaceClass.objects.create(name='Мини', sort_order=5)
    drivers = [Driver.objects.create(first_name='Пилот', last_name=f'Номер{i}', slug=f'p{i}') for i in range(3)]
    for cls, laps in ((kz, [(62000, 21000, 20000, 20900), (62500, 21100, 20100, 21000)]),
                      (mini, [(70000, None, None, None)])):
        page = root.add_child(instance=EventPage(title=f'Этап {cls.name}', slug=f'e-{cls.pk}', track=track))
        EventOccurrence.objects.create(event=page, start=timezone.make_aware(datetime.datetime(2026, 6, 14, 9)),
                                       end=timezone.make_aware(datetime.datetime(2026, 6, 14, 18)))
        group = RaceClassResultGroup.objects.create(page=page, race_class=cls)
        for i, (lap, s1, s2, s3) in enumerate(laps):
            RaceResult.objects.create(group=group, driver=drivers[i], position=i + 1, qual_best_lap_ms=lap,
                                      qual_s1_ms=s1, qual_s2_ms=s2, qual_s3_ms=s3)
    return track


def test_load_rows_reads_sessions_and_dates(track):
    rows = st.load_rows(track)
    assert len(rows) == 3
    r = next(x for x in rows if x['sessions']['qual']['lap'] == 62000)
    assert r['date'] == datetime.date(2026, 6, 14) and r['sessions']['qual']['sec'] == [21000, 20000, 20900]


def test_dq_session_is_excluded_from_records(track):
    RaceResult.objects.filter(qual_best_lap_ms=62000).update(qual_status='DQ')
    classes = st.build_track_classes(st.load_rows(track))
    kz = next(c for c in classes if c['name'] == 'KZ2')
    assert kz['record']['ms'] == 62500 and kz['starts'] == 2


def test_track_page_renders_classes_and_figures(client, track):
    r = client.get('/tracks/argamak/')
    html = r.content.decode()
    assert r.status_code == 200
    assert html.count('class="gl-tr-chip"') == 2
    assert 'data-class-id="{}" aria-pressed="true"'.format(RaceClass.objects.get(name='KZ2').pk) in html
    assert '1:02.000' in html and 'Против часовой' in html and '1 248' in html
    assert 'id="track-data"' in html
    # схемы нет — нет кнопки PDF и 3D
    assert 'scheme.pdf' not in html and 'glTrBtn3d' not in html
    # meta-description без двойных кавычек
    assert '««' not in html and '»»' not in html


def test_class_param_selects_class(client, track):
    mini = RaceClass.objects.get(name='Мини')
    html = client.get(f'/tracks/argamak/?class={mini.pk}').content.decode()
    assert f'data-class-id="{mini.pk}" aria-pressed="true"' in html
    assert 'Нет данных по секторам' in html


def test_scheme_pdf_404_without_scheme(client, track):
    assert client.get('/tracks/argamak/scheme.pdf').status_code == 404


def editor_user(perm=True):
    u = User.objects.create_user('editor', 'e@x.ru', 'x', is_staff=True)
    u.user_permissions.add(Permission.objects.get(codename='access_admin'))
    if perm:
        u.user_permissions.add(Permission.objects.get(codename='change_track'))
    return u


def test_editor_requires_change_track(client, track):
    client.force_login(editor_user(perm=False))
    assert client.get(f'/admin/track-scheme/{track.pk}/').status_code == 403
    assert client.post(f'/admin/track-scheme/{track.pk}/save/', '{}', content_type='application/json').status_code == 403


def test_editor_save_builds_svg_on_server_and_page_shows_scheme(client, track):
    client.force_login(editor_user())
    assert client.get(f'/admin/track-scheme/{track.pk}/').status_code == 200
    payload = {**make_scheme(), 'svg': '<script>alert(1)</script>'}
    r = client.post(f'/admin/track-scheme/{track.pk}/save/', json.dumps(payload), content_type='application/json')
    assert r.status_code == 200, r.content
    track.refresh_from_db()
    assert track.has_scheme and '<script' not in track.scheme_svg and track.scheme_updated_at
    assert track.effective_turns_count == 3
    html = client.get('/tracks/argamak/').content.decode()
    assert 'id="glTrPlate"' in html and 'scheme.pdf' in html and 'glTrBtn3d' in html


def test_editor_rejects_bad_scheme(client, track):
    client.force_login(editor_user())
    r = client.post(f'/admin/track-scheme/{track.pk}/save/', json.dumps({'points': [[0, 0]]}),
                    content_type='application/json')
    assert r.status_code == 400 and 'опорных точек' in r.json()['error']


def test_reference_is_private(client, track, tmp_path, monkeypatch):
    from website.feedback.storage import PrivateStorage
    monkeypatch.setattr(Track._meta.get_field('scheme_reference'), 'storage', PrivateStorage(location=str(tmp_path)))
    client.force_login(editor_user())
    png = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
           b'\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82')
    from django.core.files.uploadedfile import SimpleUploadedFile
    r = client.post(f'/admin/track-scheme/{track.pk}/reference/', {'file': SimpleUploadedFile('a.png', png)})
    assert r.status_code == 200, r.content
    assert client.get(f'/admin/track-scheme/{track.pk}/reference/').status_code == 200
    client.logout()
    assert client.get(f'/admin/track-scheme/{track.pk}/reference/').status_code in (302, 403)
    with pytest.raises(ValueError):
        Track.objects.get(pk=track.pk).scheme_reference.url
