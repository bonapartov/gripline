"""
Сквозная матрица: каждый способ регистрации/заявки, реальные views, реальная отправка.

Письма — locmem; Telegram — настоящий путь notify_admin_chat → tg_sync.api_call (перехват
на уровне Bot API, потоки выполняются синхронно). Для каждого сценария проверяем, что и кому
ушло: заявителю, админу (письмо + чат) — и что в чат не попали ПД.
"""
import re

import pytest
from django.test import Client
from django.contrib.auth.models import User
from django.core import mail

from accounts.models import DriverClaim
from website.feedback import notify, tg_sync
from website.models import Driver, FeedbackBotSettings, Team
from teams.models import TeamClaim, TeamManager

FERNET = 'cmV6b2x2ZXpvbHZlenJlem9sdmV6b2x2ZXpvbHZlenI='
TOKEN = '123456789:AAFabcdefghijklmnopqrstuvwxyz0123'

SUBJ_ADMIN_DRIVER = '[Gripline] Новая заявка на управление пилотом'
SUBJ_ADMIN_TEAM = '[Gripline] Новая заявка от команды'
SUBJ_ADMIN_REG = '[Gripline] Новая регистрация пилота (профиль не выбран)'

PILOT_FORM = {
    'email': 'pilot@example.ru', 'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
    'first_name': 'Иван', 'last_name': 'Смирнов', 'city': 'Казань',
}
TEAM_FORM = {'email': 'boss@example.ru', 'team_name': 'Kart Lab',
             'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123'}


@pytest.fixture(autouse=True)
def env(db, settings, monkeypatch):
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.BASE_URL = 'https://gripline.ru'
    settings.FEEDBACK_FERNET_KEY = FERNET
    cfg = FeedbackBotSettings.get()
    cfg.set_token(TOKEN)
    cfg.admin_chat_id = -1001
    cfg.save()

    class SyncThread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(notify.threading, 'Thread', SyncThread)
    calls = []
    monkeypatch.setattr(tg_sync, 'api_call', lambda token, method, proxy=None, payload=None, timeout=0:
                        calls.append(payload['text']) or {})
    return calls


@pytest.fixture
def tg(env):
    return env


@pytest.fixture
def commit(django_capture_on_commit_callbacks):
    return lambda: django_capture_on_commit_callbacks(execute=True)


def subjects():
    return [m.subject for m in mail.outbox]


def mails(part, to=None):
    return [m for m in mail.outbox if part in m.subject and (to is None or m.to == [to])]


def assert_no_pii(tg, *private):
    for text in tg:
        for p in private:
            assert p not in text, f'ПД «{p}» попали в Telegram: {text}'


def link(subject_part, to, prefix):
    """Путь ссылки подтверждения из письма (без хоста)."""
    letter = mails(subject_part, to)[-1]
    url = re.search(r'https?://[^\s"<]+' + re.escape(prefix) + r'[^\s"<]+', letter.body).group(0)
    return re.sub(r'^https?://[^/]+', '', url)


def pilot_link():
    return link('Подтверждение регистрации на Gripline', 'pilot@example.ru', '/accounts/verify-email/')


def team_link():
    return link('Подтверждение регистрации команды', 'boss@example.ru', '/teams/verify-email/')


def login(client, email, password='Str0ng-pass-123', path='/accounts/login/', **extra):
    return client.post(path, {'email': email, 'password': password}, **extra)


# ===================== ПИЛОТ: регистрация по email с подтверждением =====================

def test_pilot_register_sends_only_verification_mail_and_blocks_login(client, tg, commit):
    with commit():
        r = client.post('/accounts/register/', PILOT_FORM)
    assert r.status_code == 302
    user = User.objects.get(email='pilot@example.ru')
    assert user.is_active and user.profile.email_verified is False
    assert DriverClaim.objects.count() == 0
    assert len(mails('Подтверждение регистрации на Gripline', 'pilot@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 0 and SUBJ_ADMIN_REG not in subjects() and tg == []
    # до подтверждения войти нельзя
    other = Client()
    assert login(other, 'pilot@example.ru').status_code == 302
    assert '_auth_user_id' not in other.session


def test_pilot_verify_no_name_match_creates_claim_from_another_browser(client, tg, commit):
    with commit():
        client.post('/accounts/register/', PILOT_FORM)
    mail.outbox[:] = [m for m in mail.outbox if 'Подтверждение' in m.subject]
    phone = Client()                                  # ссылку открыли в другом браузере — сессии нет
    with commit():
        r = phone.get(pilot_link())
    assert r.status_code == 302
    user = User.objects.get(email='pilot@example.ru')
    assert user.profile.email_verified
    claim = DriverClaim.objects.get()
    assert claim.status == 'pending' and claim.driver is None and claim.requested_city == 'Казань'
    assert len(mails('принята на рассмотрение', 'pilot@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 1 and SUBJ_ADMIN_REG not in subjects()
    assert len(tg) == 1 and 'Новая заявка пилота' in tg[0]
    assert_no_pii(tg, 'pilot@example.ru', 'Смирнов')
    with commit():
        phone.get(pilot_link())                       # повторный клик ничего не дублирует
    assert DriverClaim.objects.count() == 1 and subjects().count(SUBJ_ADMIN_DRIVER) == 1 and len(tg) == 1
    assert login(Client(), 'pilot@example.ru').status_code == 302   # теперь вход работает


@pytest.mark.parametrize('choose', ['existing', 'none'])
def test_pilot_verify_with_name_match_then_select(client, tg, commit, choose):
    driver = Driver.objects.create(first_name='Иван', last_name='Смирнов', slug='ivan-smirnov')
    with commit():
        client.post('/accounts/register/', PILOT_FORM)
    browser = Client()
    with commit():
        r = browser.get(pilot_link())
    # заявки ещё нет; админ знает о регистрации; человека ведут на вход, потом на выбор профиля
    assert DriverClaim.objects.count() == 0
    assert r['Location'].startswith('/accounts/login/?next=/accounts/select-driver/')
    assert subjects().count(SUBJ_ADMIN_REG) == 1 and len(tg) == 1 and 'Новая регистрация пилота' in tg[0]
    with commit():
        browser.post('/accounts/login/?next=/accounts/select-driver/',
                     {'email': 'pilot@example.ru', 'password': 'Str0ng-pass-123'})
        browser.post('/accounts/select-driver/', {'driver_id': driver.pk if choose == 'existing' else 'none'})
    claim = DriverClaim.objects.get()
    assert (claim.driver == driver) if choose == 'existing' else (claim.driver is None)
    assert len(mails('принята на рассмотрение', 'pilot@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 1 and len(tg) == 2
    assert_no_pii(tg, 'pilot@example.ru', 'Смирнов')


def test_pilot_claim_approval_and_rejection_emails(tg, commit):
    user = User.objects.create_user('pilot', 'pilot@example.ru', 'x', first_name='Иван', last_name='Смирнов')
    driver = Driver.objects.create(first_name='Иван', last_name='Смирнов', slug='ivan-smirnov')
    with commit():
        claim = DriverClaim.objects.create(user=user, requested_first_name='Иван', requested_last_name='Смирнов')
    mail.outbox.clear()
    claim.driver, claim.status = driver, 'approved'
    claim.save()
    claim.save()
    assert len(mails('подтверждена', 'pilot@example.ru')) == 1
    user.profile.refresh_from_db()
    assert 'pilot' in user.profile.roles and user.profile.verified and user.profile.driver == driver

    other = User.objects.create_user('o', 'other@example.ru', 'pass-12345')
    c2 = DriverClaim.objects.create(user=other, requested_first_name='Пётр', requested_last_name='Иванов')
    mail.outbox.clear()
    c2.status, c2.admin_comment = 'rejected', 'не подтвердили личность'
    c2.save()
    rej = mails('отклонена', 'other@example.ru')
    assert len(rej) == 1 and 'не подтвердили личность' in rej[0].body


# ===================== Блокировка и «письмо не подтверждено» =====================

@pytest.fixture
def banned(db):
    user = User.objects.create_user('banned', 'banned@example.ru', 'Str0ng-pass-123',
                                    first_name='Иван', last_name='Смирнов', is_active=False)
    user.profile.email_verified = False
    user.profile.save()
    return user


def test_blocked_account_is_not_reactivated_by_verification_link_or_resend(client, banned, tg, commit, monkeypatch):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode
    from django.http import HttpResponse
    monkeypatch.setattr('accounts.views.render', lambda request, template, *a, **kw: HttpResponse(template))
    uid, token = urlsafe_base64_encode(force_bytes(banned.pk)), default_token_generator.make_token(banned)
    with commit():
        r = client.get(f'/accounts/verify-email/{uid}/{token}/')
    banned.refresh_from_db()
    assert r.content == b'accounts/verification_failed.html'
    assert not banned.is_active and banned.profile.email_verified is False
    assert DriverClaim.objects.count() == 0
    # повторная отправка: ответ как для любого адреса, но письма нет
    r = client.post('/accounts/resend-verification/', {'email': 'banned@example.ru'})
    assert r.status_code == 302 and mails('Подтверждение', 'banned@example.ru') == []
    attempt = Client()
    login(attempt, 'banned@example.ru')
    assert '_auth_user_id' not in attempt.session


def test_resend_gives_same_answer_for_any_address(client, db):
    from django.contrib.messages import get_messages
    pending = User.objects.create_user('p', 'p@example.ru', 'x')
    pending.profile.email_verified = False
    pending.profile.save()
    User.objects.create_user('v', 'v@example.ru', 'x')          # подтверждённый
    texts = set()
    for email in ('p@example.ru', 'v@example.ru', 'nobody@example.ru'):
        r = client.post('/accounts/resend-verification/', {'email': email})
        texts.add([str(m) for m in get_messages(r.wsgi_request)][-1])
    assert len(texts) == 1                                       # не различает «есть/нет/уже подтверждён»
    assert len(mails('Подтверждение', 'p@example.ru')) == 1
    assert mails('Подтверждение', 'v@example.ru') == [] and mails('Подтверждение', 'nobody@example.ru') == []


@pytest.mark.parametrize('path', ['/accounts/login/', '/teams/login/', '/organizers/login/'])
def test_unverified_user_cannot_log_in_anywhere(client, path):
    user = User.objects.create_user('u', 'u@example.ru', 'Str0ng-pass-123')
    user.profile.email_verified = False
    user.profile.save()
    r = login(client, 'u@example.ru', path=path)
    assert r.status_code == 302 and 'resend' in r['Location']
    assert '_auth_user_id' not in client.session
    user.profile.email_verified = True
    user.profile.save()
    assert '_auth_user_id' in (login(client, 'u@example.ru', path=path) and client.session)


# ===================== КОМАНДА: регистрация по email с подтверждением =====================

def test_team_register_verify_no_match_creates_claim_in_another_browser(client, tg, commit):
    with commit():
        client.post('/teams/register/', TEAM_FORM)
    user = User.objects.get(email='boss@example.ru')
    assert user.is_active and not user.profile.email_verified and user.profile.pending_team_name == 'Kart Lab'
    assert TeamClaim.objects.count() == 0 and tg == []
    assert login(Client(), 'boss@example.ru', path='/teams/login/').status_code == 302
    phone = Client()
    with commit():
        phone.get(team_link())
    claim = TeamClaim.objects.get()
    assert claim.status == 'pending' and claim.team is None and claim.requested_team_name == 'Kart Lab'
    user.profile.refresh_from_db()
    assert user.profile.email_verified and user.profile.pending_team_name == ''
    assert len(mails('принята на рассмотрение', 'boss@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_TEAM) == 1 and len(tg) == 1
    assert_no_pii(tg, 'boss@example.ru')
    with commit():
        phone.get(team_link())                        # повторный клик
    assert TeamClaim.objects.count() == 1 and subjects().count(SUBJ_ADMIN_TEAM) == 1


@pytest.mark.parametrize('choice', ['existing', 'none'])
def test_team_register_verify_match_then_select(client, tg, commit, choice):
    team = Team.objects.create(name='Kart Lab Racing')
    with commit():
        client.post('/teams/register/', TEAM_FORM)
    browser = Client()
    with commit():
        r = browser.get(team_link())
    assert TeamClaim.objects.count() == 0
    assert r['Location'].startswith('/accounts/login/?next=/teams/select-team/')
    with commit():
        browser.post('/accounts/login/?next=/teams/select-team/',
                     {'email': 'boss@example.ru', 'password': 'Str0ng-pass-123'})
        browser.post('/teams/select-team/', {'team_id': team.pk if choice == 'existing' else 'none'})
    claim = TeamClaim.objects.get()
    assert (claim.team == team) if choice == 'existing' else (claim.team is None)
    assert len(mails('принята на рассмотрение', 'boss@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_TEAM) == 1 and len(tg) == 1


def test_team_claim_approval_gives_manager_role_and_email(tg, commit):
    user = User.objects.create_user('boss', 'boss@example.ru', 'x')
    with commit():
        claim = TeamClaim.objects.create(user=user, requested_team_name='Kart Lab')
    team = Team.objects.create(name='Kart Lab')
    mail.outbox.clear()
    claim.team, claim.status = team, 'approved'
    claim.save()
    assert TeamManager.objects.filter(user=user, team=team, is_active=True).exists()
    user.profile.refresh_from_db()
    assert 'manager' in user.profile.roles and user.profile.team == team
    assert len(mails('подтверждена', 'boss@example.ru')) == 1


def test_team_claim_rejection_email(tg, commit):
    user = User.objects.create_user('boss', 'boss@example.ru', 'x')
    with commit():
        claim = TeamClaim.objects.create(user=user, requested_team_name='Kart Lab')
    mail.outbox.clear()
    claim.status, claim.admin_comment = 'rejected', 'такая команда уже есть'
    claim.save()
    rej = mails('отклонена', 'boss@example.ru')
    assert len(rej) == 1 and 'такая команда уже есть' in rej[0].body
    assert not TeamManager.objects.exists()


# ===================== Яндекс/VK/Telegram: онбординг после OAuth =====================

@pytest.fixture
def social_user(db):
    return User.objects.create_user('ya_1', 'ya@example.ru', 'x', first_name='Пётр', last_name='Иванов')


def test_yandex_pilot_select_existing(client, social_user, tg, commit):
    driver = Driver.objects.create(first_name='Пётр', last_name='Иванов', slug='petr-ivanov')
    client.force_login(social_user)
    with commit():
        client.post('/accounts/yandex/onboarding/pilot/', {'action': 'select', 'driver_id': driver.pk})
    assert DriverClaim.objects.get().driver == driver
    assert len(mails('принята на рассмотрение', 'ya@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 1 and len(tg) == 1
    assert_no_pii(tg, 'ya@example.ru', 'Иванов')


def test_yandex_pilot_new_profile(client, social_user, tg, commit):
    client.force_login(social_user)
    with commit():
        client.post('/accounts/yandex/onboarding/pilot/', {'action': 'new', 'first_name': 'Пётр', 'last_name': 'Иванов'})
    assert DriverClaim.objects.get().status == 'pending'
    assert Driver.objects.filter(last_name='Иванов').count() == 1
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 1 and len(tg) == 1
    assert_no_pii(tg, 'Иванов', 'ya@example.ru')


def test_yandex_pilot_preselected_in_choose_role(client, social_user, tg, commit):
    driver = Driver.objects.create(first_name='Пётр', last_name='Иванов', slug='petr-ivanov')
    client.force_login(social_user)
    session = client.session
    session['yandex_preselected_pilot_id'] = driver.pk
    session.save()
    with commit():
        client.get('/accounts/yandex/onboarding/pilot/')
    assert DriverClaim.objects.get().driver == driver
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 1 and len(tg) == 1


def test_yandex_team_select_existing(client, social_user, tg, commit):
    team = Team.objects.create(name='Kart Lab')
    client.force_login(social_user)
    with commit():
        client.post('/accounts/yandex/onboarding/team/', {'action': 'select', 'team_id': team.pk})
    assert TeamClaim.objects.get().team == team
    assert TeamManager.objects.count() == 0                        # менеджер — только после подтверждения
    assert len(mails('принята на рассмотрение', 'ya@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_TEAM) == 1 and len(tg) == 1
    assert_no_pii(tg, 'ya@example.ru')


def test_yandex_new_team_waits_for_approval_then_creates_team_and_manager(client, social_user, tg, commit):
    client.force_login(social_user)
    with commit():
        client.post('/accounts/yandex/onboarding/team/', {'action': 'new', 'team_name': 'Fresh', 'city': 'Казань'})
    claim = TeamClaim.objects.get()
    # до одобрения: ни команды на сайте, ни прав менеджера
    assert claim.team is None and claim.requested_city == 'Казань'
    assert not Team.objects.filter(name='Fresh').exists() and TeamManager.objects.count() == 0
    social_user.profile.refresh_from_db()
    assert 'manager' not in social_user.profile.roles
    assert subjects().count(SUBJ_ADMIN_TEAM) == 1 and len(tg) == 1
    # одобрение админом
    mail.outbox.clear()
    claim.status = 'approved'
    claim.save()
    team = Team.objects.get(name='Fresh')
    assert team.city == 'Казань' and TeamManager.objects.filter(user=social_user, team=team, is_active=True).exists()
    social_user.profile.refresh_from_db()
    assert 'manager' in social_user.profile.roles
    assert len(mails('подтверждена', 'ya@example.ru')) == 1


def test_yandex_new_team_rejected_leaves_no_trace(client, social_user, tg, commit):
    client.force_login(social_user)
    with commit():
        client.post('/accounts/yandex/onboarding/team/', {'action': 'new', 'team_name': 'Spam Team'})
    claim = TeamClaim.objects.get()
    claim.status = 'rejected'
    claim.save()
    assert not Team.objects.filter(name='Spam Team').exists() and TeamManager.objects.count() == 0


def test_yandex_team_preselected_name_and_id(client, social_user, tg, commit):
    client.force_login(social_user)
    session = client.session
    session['yandex_preselected_team_name'] = 'Preselected'
    session.save()
    with commit():
        client.get('/accounts/yandex/onboarding/team/')
    claim = TeamClaim.objects.get()
    assert claim.team is None and claim.requested_team_name == 'Preselected'
    assert not Team.objects.filter(name='Preselected').exists()
    assert subjects().count(SUBJ_ADMIN_TEAM) == 1 and len(tg) == 1

    other = User.objects.create_user('ya_2', 'ya2@example.ru', 'x')
    team = Team.objects.create(name='Existing')
    client.force_login(other)
    session = client.session
    session['yandex_preselected_team_id'] = team.pk
    session.save()
    with commit():
        client.get('/accounts/yandex/onboarding/team/')
    assert TeamClaim.objects.filter(user=other, team=team).count() == 1
    assert subjects().count(SUBJ_ADMIN_TEAM) == 2 and len(tg) == 2


def test_social_user_without_email_gets_no_user_mail_but_admin_still_notified(client, tg, commit):
    tg_user = User.objects.create_user('tg_777', '', 'x')
    driver = Driver.objects.create(first_name='Пётр', last_name='Иванов', slug='petr-ivanov')
    client.force_login(tg_user)
    with commit():
        client.post('/accounts/yandex/onboarding/pilot/', {'action': 'select', 'driver_id': driver.pk})
    assert [m for m in mail.outbox if m.to == ['']] == []
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 1 and len(tg) == 1


def test_social_user_is_verified_by_default(social_user):
    assert social_user.profile.email_verified is True


# ===================== Организатор: подтверждение email =====================

def test_organizer_register_requires_verification_and_makes_no_claims(client, tg, commit, monkeypatch):
    from django.http import HttpResponse
    monkeypatch.setattr('organizers.views.render', lambda request, template, *a, **kw: HttpResponse(template))
    with commit():
        client.post('/organizers/register/', {
            'email': 'org@example.ru', 'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
            'first_name': 'Олег', 'last_name': 'Клубов', 'phone': '+79990000000', 'telegram': '@club',
        })
    user = User.objects.get(email='org@example.ru')
    assert user.is_active and user.profile.email_verified is False
    assert len(mails('Подтверждение', 'org@example.ru')) == 1
    assert login(Client(), 'org@example.ru', path='/organizers/login/').status_code == 302
    Client().get(link('Подтверждение', 'org@example.ru', '/organizers/verify-email/'))
    user.profile.refresh_from_db()
    assert user.profile.email_verified and hasattr(user, 'organizer_profile')
    assert DriverClaim.objects.count() == 0 and TeamClaim.objects.count() == 0 and tg == []


# ===================== Занятый email: тот же ответ, что и для нового адреса =====================

REGISTRATIONS = {
    'pilot': ('/accounts/register/', PILOT_FORM),
    'team': ('/teams/register/', TEAM_FORM),
    'organizer': ('/organizers/register/', {
        'email': 'pilot@example.ru', 'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
        'first_name': 'Олег', 'last_name': 'Клубов', 'phone': '', 'telegram': ''}),
}


def last_message(response):
    from django.contrib.messages import get_messages
    texts = [str(m) for m in get_messages(response.wsgi_request)]
    return texts[-1] if texts else None


def answer(client, kind, email):
    path, form = REGISTRATIONS[kind]
    form = {**form, 'email': email}
    r = client.post(path, form)
    return r.status_code, r['Location'], last_message(r)


@pytest.mark.parametrize('kind', ['pilot', 'team', 'organizer'])
def test_registration_answer_is_identical_for_new_and_taken_email(kind, tg, commit, monkeypatch):
    from django.http import HttpResponse
    for mod in ('accounts', 'teams', 'organizers'):
        monkeypatch.setattr(f'{mod}.views.render', lambda request, template, *a, **kw: HttpResponse(template))
    User.objects.create_user('taken', 'taken@example.ru', 'x')                     # подтверждённый
    with commit():
        fresh = answer(Client(), kind, 'fresh@example.ru')
        taken = answer(Client(), kind, 'taken@example.ru')
    assert fresh == taken, f'ответ выдаёт, занят ли адрес: {fresh} != {taken}'
    assert 'уже зарегистрирован' not in (taken[2] or '')
    assert User.objects.filter(email__iexact='taken@example.ru').count() == 1      # дубль не создан


@pytest.mark.parametrize('kind', ['pilot', 'team', 'organizer'])
def test_taken_email_owner_gets_account_exists_letter(kind, tg, commit):
    User.objects.create_user('taken', 'taken@example.ru', 'x')
    with commit():
        answer(Client(), kind, 'Taken@Example.ru')                                 # регистр не важен
    letters = mails('уже зарегистрирован', 'taken@example.ru')
    assert len(letters) == 1 and mails('Подтверждение', 'taken@example.ru') == []
    from django.urls import resolve
    for path in ('/accounts/login/', '/accounts/password-reset/'):
        assert f'https://gripline.ru{path}' in letters[0].body
        resolve(path)
    assert tg == [] and DriverClaim.objects.count() == 0 and TeamClaim.objects.count() == 0


@pytest.mark.parametrize('kind', ['pilot', 'team', 'organizer'])
def test_taken_unverified_email_gets_fresh_verification_link(kind, tg, commit):
    user = User.objects.create_user('half', 'half@example.ru', 'x')
    user.profile.email_verified = False
    if kind == 'team':
        user.profile.pending_team_name = 'Kart Lab'
    user.profile.save()
    if kind == 'organizer':
        from organizers.models import OrganizerProfile
        OrganizerProfile.objects.create(user=user)
    with commit():
        answer(Client(), kind, 'half@example.ru')
    assert len(mails('Подтверждение', 'half@example.ru')) == 1
    assert mails('уже зарегистрирован', 'half@example.ru') == []


@pytest.mark.parametrize('kind', ['pilot', 'team', 'organizer'])
def test_taken_blocked_email_gets_no_mail_but_same_answer(kind, tg, commit, monkeypatch):
    from django.http import HttpResponse
    for mod in ('accounts', 'teams', 'organizers'):
        monkeypatch.setattr(f'{mod}.views.render', lambda request, template, *a, **kw: HttpResponse(template))
    User.objects.create_user('ban', 'ban@example.ru', 'x', is_active=False)
    with commit():
        banned = answer(Client(), kind, 'ban@example.ru')
        fresh = answer(Client(), kind, 'fresh@example.ru')
    assert banned == fresh and mails('', 'ban@example.ru') == []


def test_invalid_form_does_not_reveal_taken_email(client, monkeypatch):
    from django.http import HttpResponse
    monkeypatch.setattr('accounts.views.render', lambda request, template, *a, **kw: HttpResponse(template))
    User.objects.create_user('taken', 'taken@example.ru', 'x')
    bad = {**PILOT_FORM, 'password2': 'другой-пароль'}
    answers = []
    for email in ('taken@example.ru', 'fresh@example.ru'):
        r = Client().post('/accounts/register/', {**bad, 'email': email})
        answers.append((r.status_code, last_message(r)))
    assert answers[0] == answers[1] and 'зарегистрирован' not in (answers[0][1] or '')
    assert mail.outbox == []
