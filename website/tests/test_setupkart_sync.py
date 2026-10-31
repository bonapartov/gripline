"""Синхронизация сессий приложения и сессии в ЛК (17.10.2026, этап 2)."""
from website.tests.team_access_fixtures import confirmed_membership
import json
import secrets

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache

from teams.models import TeamManager
from website.models import AppDeviceToken, AppSyncRecord, AppSyncRecordVersion, Driver, Team, TeamMembership, Track
from website.setupkart.auth import TOKEN_PREFIX, _hash

PUSH = '/api/setupkart/sync/push/'
PULL = '/api/setupkart/sync/pull/'


@pytest.fixture(autouse=True)
def env(db, settings):
    cache.clear()
    settings.WAGTAIL_CACHE = False
    from django.conf import settings as dj
    from wagtail.coreutils import get_supported_content_language_variant
    from wagtail.models import Locale, Page, Site
    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(dj.LANGUAGE_CODE))
    Site.objects.create(hostname='testserver', root_page=Page.add_root(title='Root', slug='root'), is_default_site=True)


def make_user(email, driver=None):
    user = User.objects.create_user(username=email, email=email, password='x', first_name='Иван', last_name='Петров')
    profile = user.profile
    profile.email_verified = True
    profile.save()
    if driver:
        from accounts.models import DriverClaim
        DriverClaim.objects.create(user=user, driver=driver, status='approved')
    return user


def token_for(user):
    token = TOKEN_PREFIX + secrets.token_urlsafe(16)
    AppDeviceToken.objects.create(user=user, key_hash=_hash(token))
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


def session_row(uuid='s1', updated=1000, driver_id=None, track='t1', draft=False, deleted=None, name='Тренировка'):
    setup = {'driver': 'Иван Петров', 'engine_category': 'Rotax Senior', 'main_jet': '122',
             'pressure.fl.cold': 0.55, 'laps': [61000, 60500]}
    if driver_id:
        setup['driver_id'] = driver_id
    return {'id': uuid, 'kartId': 'k1', 'engineId': 'e1', 'trackId': track, 'startedAt': 1760000000000,
            'name': name, 'setupJson': json.dumps(setup), 'bestTimeMs': 60500, 'isDraft': draft,
            'updatedAt': updated, 'createdAt': 1, 'deletedAt': deleted, 'profileVersion': 1, 'isFavorite': False}


def push(client, auth, **tables):
    return client.post(PUSH, json.dumps({'schema_version': 9, 'tables': tables}), content_type='application/json', **auth)


def test_push_and_pull_roundtrip(client):
    track = Track.objects.create(name='Ижорец')
    user = make_user('a@example.com')
    auth = token_for(user)
    r = push(client, auth, karts=[{'id': 'k1', 'name': 'Tony', 'updatedAt': 5}],
             tracks=[{'id': 't1', 'name': 'Ижорец', 'source': 'base', 'baseId': track.pk, 'updatedAt': 5}],
             sessions=[session_row()])
    assert r.json() == {'accepted': 3, 'skipped': 0}
    rec = AppSyncRecord.objects.get(table='sessions')
    assert rec.track_id == track.pk and rec.started_at is not None
    data = client.get(PULL, **auth).json()
    assert [x['row']['id'] for x in data['tables']['sessions']] == ['s1']
    assert data['more'] is False
    again = client.get(PULL, {'since': data['cursor']}, **auth).json()
    assert all(not v for v in again['tables'].values())


def test_newer_wins_older_ignored_history_kept(client):
    user = make_user('a@example.com')
    auth = token_for(user)
    push(client, auth, sessions=[session_row(updated=1000, name='A')])
    assert push(client, auth, sessions=[session_row(updated=900, name='old')]).json()['skipped'] == 1
    assert push(client, auth, sessions=[session_row(updated=2000, name='B')]).json()['accepted'] == 1
    rec = AppSyncRecord.objects.get()
    assert rec.data['name'] == 'B'
    assert AppSyncRecordVersion.objects.get(record=rec).data['name'] == 'A'


def test_drafts_not_synced_and_deleted_marked(client):
    user = make_user('a@example.com')
    auth = token_for(user)
    assert push(client, auth, sessions=[session_row(draft=True)]).json()['skipped'] == 1
    push(client, auth, sessions=[session_row(deleted=5)])
    assert AppSyncRecord.objects.get().deleted


def test_driver_only_own_or_team_roster(client):
    me = Driver.objects.create(first_name='Иван', last_name='Петров')
    mate = Driver.objects.create(first_name='Анна', last_name='Сидорова')
    stranger = Driver.objects.create(first_name='Чужой', last_name='Пилот')
    user = make_user('a@example.com', driver=me)
    team = Team.objects.create(name='Гонщики')
    TeamManager.objects.create(user=user, team=team)
    confirmed_membership(driver=mate, team=team)
    auth = token_for(user)
    push(client, auth, sessions=[session_row('s1', driver_id=me.pk), session_row('s2', driver_id=mate.pk),
                                 session_row('s3', driver_id=stranger.pk)])
    got = dict(AppSyncRecord.objects.values_list('uuid', 'driver_id'))
    assert got == {'s1': me.pk, 's2': mate.pk, 's3': None}


def test_users_isolated(client):
    a, b = make_user('a@example.com'), make_user('b@example.com')
    push(client, token_for(a), sessions=[session_row()])
    assert client.get(PULL, **token_for(b)).json()['tables']['sessions'] == []
    assert client.post(PUSH, '{}', content_type='application/json').status_code == 401


def test_pull_pagination(client, monkeypatch):
    from website.setupkart import sync
    monkeypatch.setattr(sync, 'PULL_LIMIT', 2)
    user = make_user('a@example.com')
    auth = token_for(user)
    push(client, auth, sessions=[session_row(f's{i}') for i in range(5)])
    seen, since = [], ''
    for _ in range(5):
        data = client.get(PULL, {'since': since} if since else {}, **auth).json()
        seen += [x['row']['id'] for x in data['tables']['sessions']]
        since = data['cursor']
        if not data['more']:
            break
    assert sorted(seen) == [f's{i}' for i in range(5)]


def _team_setup():
    pilot_driver = Driver.objects.create(first_name='Анна', last_name='Сидорова')
    pilot = make_user('pilot@example.com', driver=pilot_driver)
    manager = make_user('manager@example.com')
    team = Team.objects.create(name='Гонщики')
    TeamManager.objects.create(user=manager, team=team)
    confirmed_membership(driver=pilot_driver, team=team)
    return pilot, pilot_driver, manager


def test_lk_own_list_and_detail(client):
    pilot, driver, _ = _team_setup()
    push(client, token_for(pilot), sessions=[session_row(driver_id=driver.pk)])
    client.force_login(pilot)
    page = client.get('/accounts/app-sessions/').content.decode()
    assert 'Тренировка' in page and 'Тр' in page
    detail = client.get('/accounts/app-sessions/s1/').content.decode()
    assert 'Главный жиклёр' in detail and '122' in detail
    assert 'ПЛ хол.: 0.55' in detail
    assert '2 кр., лучший 1:00.500' in detail


def test_team_sees_pilot_sessions_unless_hidden(client):
    pilot, driver, manager = _team_setup()
    push(client, token_for(pilot), sessions=[session_row('s1', driver_id=driver.pk), session_row('s2', driver_id=driver.pk)])
    client.force_login(manager)
    assert client.get('/accounts/app-sessions/s1/').status_code == 200
    # пилот скрыл одну сессию
    client.force_login(pilot)
    client.post('/accounts/app-sessions/s2/visibility/', {'public': ''})
    client.force_login(manager)
    assert client.get('/accounts/app-sessions/s2/').status_code == 404
    page = client.get('/teams/app-sessions/').content.decode()
    assert '/accounts/app-sessions/s1/' in page and '/accounts/app-sessions/s2/' not in page
    # пилот выключил показ команде целиком
    client.force_login(pilot)
    client.post('/accounts/app-sessions/', {'public': ''})
    client.force_login(manager)
    assert client.get('/accounts/app-sessions/s1/').status_code == 404


def test_left_team_hides_sessions(client):
    pilot, driver, manager = _team_setup()
    push(client, token_for(pilot), sessions=[session_row(driver_id=driver.pk)])
    TeamMembership.objects.filter(driver=driver).update(is_active=False)
    client.force_login(manager)
    assert client.get('/accounts/app-sessions/s1/').status_code == 404


def test_stranger_cannot_open_or_change(client):
    pilot, driver, _ = _team_setup()
    push(client, token_for(pilot), sessions=[session_row(driver_id=driver.pk)])
    other = make_user('other@example.com')
    client.force_login(other)
    assert client.get('/accounts/app-sessions/s1/').status_code == 404
    assert client.post('/accounts/app-sessions/s1/visibility/', {'team': '1'}).status_code == 404


# ───── Этап 4: этап по протоколу, аналитика, сравнение, страница пилота ─────

def _event_with_result(driver, track, day, position=3, best=59800):
    """Этап на трассе [track] в день [day] с результатом пилота в протоколе."""
    import datetime
    from django.utils import timezone as tz
    from wagtail.models import Page
    from website.models import EventOccurrence, EventPage, RaceClass, RaceClassResultGroup, RaceResult
    root = Page.objects.get(depth=1)
    event = root.add_child(instance=EventPage(title='1 этап', slug='stage-1', track=track))
    start = tz.make_aware(datetime.datetime.combine(day, datetime.time(9)))
    EventOccurrence.objects.create(event=event, start=start, end=start + datetime.timedelta(hours=8))
    klass = RaceClass.objects.create(name='Rotax Senior')
    group = RaceClassResultGroup.objects.create(page=event, race_class=klass)
    RaceResult.objects.create(group=group, driver=driver, position=position, best_lap_ms=best)
    return event


def test_session_on_race_day_shows_protocol_result(client):
    import datetime
    track = Track.objects.create(name='Ижорец')
    pilot, driver, _ = _team_setup()
    auth = token_for(pilot)
    row = session_row(driver_id=driver.pk)
    day = datetime.datetime.fromtimestamp(row['startedAt'] / 1000).date()
    _event_with_result(driver, track, day)
    push(client, auth, tracks=[{'id': 't1', 'name': 'Ижорец', 'source': 'base', 'baseId': track.pk, 'updatedAt': 5}],
         sessions=[row])
    client.force_login(pilot)
    page = client.get('/accounts/app-sessions/s1/').content.decode()
    assert 'В этот день — этап' in page and '3 место' in page and '59.800' in page
    assert '1 этап' in client.get('/accounts/app-sessions/').content.decode()


def test_analytics_and_compare_pages(client):
    pilot, driver, _ = _team_setup()
    auth = token_for(pilot)
    rows = []
    for i, (jet, best) in enumerate([(120, 61000), (122, 60500), (124, 60900)]):
        r = session_row(f's{i}', driver_id=driver.pk, name=f'Заезд {i}')
        setup = json.loads(r['setupJson'])
        setup['main_jet'] = str(jet)
        r['setupJson'] = json.dumps(setup)
        r['bestTimeMs'] = best
        r['startedAt'] += i * 3600_000
        rows.append(r)
    push(client, auth, sessions=rows)
    client.force_login(pilot)
    page = client.get('/accounts/app-sessions/analytics/', {'x': 'main_jet'}).content.decode()
    assert 'glSessScatterData' in page and 'Главный жиклёр' in page
    assert 'Главный жиклёр: 120 → 122' in page  # «что меняли → что дало»
    cmp = client.get('/accounts/app-sessions/compare/', {'a': 's0', 'b': 's1'}).content.decode()
    assert 'class="gl-sess-diff"' in cmp and '120' in cmp and '122' in cmp
    # чужую сессию сравнить нельзя
    other = make_user('x@example.com')
    client.force_login(other)
    assert 'class="gl-sess-diff"' not in client.get('/accounts/app-sessions/compare/', {'a': 's0', 'b': 's1'}).content.decode()


def test_public_trainings_only_when_pilot_allows():
    from website.setupkart.public import training_sessions
    from django.test import Client
    client = Client()
    pilot, driver, manager = _team_setup()
    push(client, token_for(pilot), sessions=[session_row('own', driver_id=driver.pk)])
    push(client, token_for(manager), sessions=[session_row('by-manager', driver_id=driver.pk)])
    assert training_sessions(driver) == []
    AppSyncRecord.objects.update(public=True)
    assert training_sessions(driver) == [], 'общее разрешение выключено'
    from accounts.models import UserProfile
    UserProfile.objects.filter(user=pilot).update(app_sessions_public=True)
    got = training_sessions(driver)
    assert len(got) == 1 and got[0]['best'] == '1:00.500', 'сессия менеджера на страницу пилота не попадает'


def test_trainings_never_reach_rating_data():
    """Рейтинг считается только по протоколам: загрузчик аналитики не знает о сессиях приложения."""
    import inspect
    from analytics.core import data_loader
    src = inspect.getsource(data_loader)
    assert 'AppSyncRecord' not in src and 'app_sessions' not in src


def test_driver_page_shows_public_trainings(client):
    from accounts.models import UserProfile
    pilot, driver, _ = _team_setup()
    push(client, token_for(pilot), sessions=[session_row(driver_id=driver.pk)])
    AppSyncRecord.objects.update(public=True)
    UserProfile.objects.filter(user=pilot).update(app_sessions_public=True)
    page = client.get(driver.get_absolute_url())
    assert page.status_code == 200
    html = page.content.decode()
    assert 'Тренировки' in html and '1:00.500' in html
    assert 'Главный жиклёр' not in html, 'настройки карта на публичной странице не показываются'
