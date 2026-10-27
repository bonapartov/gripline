"""Вход в приложение GripLine SetupKart аккаунтом сайта (17.10.2026)."""
import re
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache

from accounts.models import DriverClaim
from teams.models import TeamManager
from website.models import AppDeviceToken, Driver, Team, TeamMembership
from website.setupkart.auth import SESSION_KEY, challenge_of

START = '/api/setupkart/auth/start/'
COMPLETE = '/api/setupkart/auth/complete/'
EXCHANGE = '/api/setupkart/auth/exchange/'
ME = '/api/setupkart/auth/me/'
LOGOUT = '/api/setupkart/auth/logout/'


@pytest.fixture(autouse=True)
def env(db, settings):
    cache.clear()
    settings.BASE_URL = 'https://gripline.ru'
    settings.WAGTAIL_CACHE = False
    from django.conf import settings as dj
    from wagtail.coreutils import get_supported_content_language_variant
    from wagtail.models import Locale, Page, Site
    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(dj.LANGUAGE_CODE))
    Site.objects.create(hostname='testserver', root_page=Page.add_root(title='Root', slug='root'), is_default_site=True)


def make_user(email='pilot@example.com', verified=True, active=True):
    user = User.objects.create_user(username=email, email=email, password='x', first_name='Иван', last_name='Петров')
    user.is_active = active
    user.save()
    profile = user.profile
    profile.email_verified = verified
    profile.save()
    return user


def begin(client):
    verifier = secrets.token_urlsafe(48)
    state = 'st' + secrets.token_hex(6)
    return verifier, state, client.get(START, {'challenge': challenge_of(verifier), 'state': state})


def app_code(client):
    page = client.get(COMPLETE)
    assert page.status_code == 200
    link = re.search(r'href="(gripline-setupkart://login\?[^"]+)"', page.content.decode()).group(1)
    q = parse_qs(urlparse(link.replace('&amp;', '&')).query)
    return q['code'][0], q['state'][0]


def login_token(client, user):
    client.force_login(user)
    verifier, state, _ = begin(client)
    code, _ = app_code(client)
    r = client.post(EXCHANGE, {'code': code, 'verifier': verifier, 'device': 'Pixel 8'}, content_type='application/json')
    assert r.status_code == 200
    return r.json()['token']


def test_anonymous_start_goes_to_login_with_next_to_complete(client):
    _, _, r = begin(client)
    assert r.status_code == 302
    assert r['Location'].startswith('/accounts/login/?next=') and 'auth%2Fcomplete' in r['Location']


def test_full_flow_issues_token_once(client):
    user = make_user()
    client.force_login(user)
    verifier, state, r = begin(client)
    assert r['Location'] == COMPLETE
    code, got_state = app_code(client)
    assert got_state == state
    r = client.post(EXCHANGE, {'code': code, 'verifier': verifier, 'device': 'Pixel 8', 'app_version': '1.2.0'},
                    content_type='application/json')
    assert r.status_code == 200
    data = r.json()
    assert data['token'].startswith('gsk_')
    assert data['account']['email'] == user.email
    tok = AppDeviceToken.objects.get()
    assert tok.device_name == 'Pixel 8' and data['token'] not in tok.key_hash
    # код одноразовый
    r = client.post(EXCHANGE, {'code': code, 'verifier': verifier}, content_type='application/json')
    assert r.status_code == 400


def test_wrong_verifier_rejected_and_burns_code(client):
    user = make_user()
    client.force_login(user)
    verifier, _, _ = begin(client)
    code, _ = app_code(client)
    bad = client.post(EXCHANGE, {'code': code, 'verifier': secrets.token_urlsafe(48)}, content_type='application/json')
    assert bad.status_code == 400
    again = client.post(EXCHANGE, {'code': code, 'verifier': verifier}, content_type='application/json')
    assert again.status_code == 400
    assert not AppDeviceToken.objects.exists()


def test_complete_without_start_shows_error(client):
    client.force_login(make_user())
    r = client.get(COMPLETE)
    assert r.status_code == 200 and 'gripline-setupkart://' not in r.content.decode()


def test_unverified_email_gets_no_code(client):
    user = make_user(verified=False)
    client.force_login(user)
    begin(client)
    r = client.get(COMPLETE)
    assert 'gripline-setupkart://' not in r.content.decode()


def test_bad_start_params(client):
    r = client.get(START, {'challenge': 'short', 'state': 'x'})
    assert r.status_code == 400


def test_social_login_landing_in_profile_returns_to_app(client):
    user = make_user()
    client.force_login(user)
    begin(client)
    r = client.get('/accounts/profile/')
    assert r.status_code == 302 and r['Location'] == COMPLETE


def test_profile_waits_for_yandex_onboarding(client):
    user = make_user()
    client.force_login(user)
    begin(client)
    s = client.session
    s['yandex_onboarding'] = True
    s.save()
    r = client.get(COMPLETE)
    assert r['Location'] == '/accounts/profile/'
    assert SESSION_KEY in client.session


def test_me_and_logout(client):
    user = make_user()
    token = login_token(client, user)
    client.logout()
    auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
    r = client.get(ME, **auth)
    assert r.status_code == 200 and r.json()['account']['name'] == 'Иван Петров'
    assert client.post(LOGOUT, **auth).status_code == 200
    assert client.get(ME, **auth).status_code == 401


def test_blocked_user_token_stops_working(client):
    user = make_user()
    token = login_token(client, user)
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert client.get(ME, HTTP_AUTHORIZATION=f'Bearer {token}').status_code == 401


def test_me_without_token(client):
    assert client.get(ME).status_code == 401
    assert client.get(ME, HTTP_AUTHORIZATION='Bearer gsk_nope').status_code == 401


def test_account_payload_driver_and_team_pilots(client):
    user = make_user()
    driver = Driver.objects.create(first_name='Иван', last_name='Петров')
    profile = user.profile
    profile.driver = driver
    profile.verified = True
    profile.save()
    team = Team.objects.create(name='Гонщики')
    TeamManager.objects.create(user=user, team=team)
    mate = Driver.objects.create(first_name='Анна', last_name='Сидорова')
    gone = Driver.objects.create(first_name='Олег', last_name='Ушедший')
    TeamMembership.objects.create(driver=mate, team=team)
    TeamMembership.objects.create(driver=gone, team=team, is_active=False)
    token = login_token(client, user)
    acc = client.get(ME, HTTP_AUTHORIZATION=f'Bearer {token}').json()['account']
    assert acc['driver']['id'] == driver.pk and acc['driver']['url'].endswith(f'/drivers/{driver.slug}/')
    assert [p['name'] for p in acc['team_pilots']] == ['Анна Сидорова']
    assert acc['teams'] == [{'id': team.pk, 'name': 'Гонщики'}]


def test_account_payload_driver_ratings(client, monkeypatch):
    """Рейтинг по классам — из той же функции, что страница пилота; вне таблицы — без места, с причиной."""
    import datetime
    from website import views
    user = make_user()
    driver = Driver.objects.create(first_name='Иван', last_name='Петров')
    profile = user.profile
    profile.driver = driver
    profile.verified = True
    profile.save()
    token = login_token(client, user)
    auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
    assert client.get(ME, **auth).json()['account']['driver']['ratings'] == []  # рейтинга ещё нет
    cache.clear()

    calls = []

    def fake(d):
        calls.append(d.pk)
        return [
            {'class_id': 7, 'class_name': 'RM Junior', 'normalized_score': 81.4, 'rank': 3, 'total': 24,
             'inactive': False, 'out_reason': None, 'starts': 9, 'wins': 2, 'podiums': 5,
             'last_race_date': datetime.datetime(2026, 9, 14, 18, 0, tzinfo=datetime.timezone.utc)},
            {'class_id': 3, 'class_name': 'RM Mini', 'normalized_score': 55.0, 'rank': 12, 'total': 30,
             'inactive': True, 'out_reason': 'inactive', 'starts': 6, 'wins': 0, 'podiums': 1,
             'last_race_date': None},
        ]

    monkeypatch.setattr(views, '_get_driver_class_ratings', fake)
    ratings = client.get(ME, **auth).json()['account']['driver']['ratings']
    assert ratings[0] == {
        'class_id': 7, 'class_name': 'RM Junior', 'score': 81.4, 'rank': 3, 'total': 24, 'out_reason': '',
        'starts': 9, 'wins': 2, 'podiums': 5, 'last_race_date': '2026-09-14',
        'url': 'https://gripline.ru/top/drivers/?class=7',
    }
    assert ratings[1]['rank'] is None and ratings[1]['out_reason'] == 'вне рейтинга: давно не выступал'
    client.get(ME, **auth)
    assert calls == [driver.pk]  # второй запрос — из кэша


def test_unapproved_driver_not_exposed(client):
    user = make_user()
    driver = Driver.objects.create(first_name='Иван', last_name='Петров')
    profile = user.profile
    profile.driver = driver
    profile.verified = False
    profile.save()
    DriverClaim.objects.create(user=user, driver=driver, status='pending')
    token = login_token(client, user)
    acc = client.get(ME, HTTP_AUTHORIZATION=f'Bearer {token}').json()['account']
    assert acc['driver'] is None and acc['claim_pending'] is True


def test_revoke_device_from_lk(client):
    user = make_user()
    login_token(client, user)
    tok = AppDeviceToken.objects.get()
    other = make_user('other@example.com')
    client.force_login(other)
    assert client.post(f'/api/setupkart/auth/devices/{tok.pk}/revoke/').status_code == 404
    client.force_login(user)
    r = client.post(f'/api/setupkart/auth/devices/{tok.pk}/revoke/')
    assert r.status_code == 302
    tok.refresh_from_db()
    assert tok.revoked_at is not None
