"""
Сквозная матрица: каждый способ регистрации/заявки, реальные views, реальная отправка.

Письма — locmem; Telegram — настоящий путь notify_admin_chat → tg_sync.api_call (перехват
на уровне Bot API, потоки выполняются синхронно). Для каждого сценария проверяем, что и кому
ушло: заявителю, админу (письмо + чат) — и что в чат не попали ПД.
"""
import re

import pytest
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


# ===================== ПИЛОТ, регистрация по email =====================

def test_pilot_email_no_name_match(client, tg, commit):
    with commit():
        r = client.post('/accounts/register/', PILOT_FORM)
    assert r.status_code == 302
    claim = DriverClaim.objects.get(user__email='pilot@example.ru')
    assert claim.status == 'pending' and claim.driver is None
    assert len(mails('принята на рассмотрение', 'pilot@example.ru')) == 1     # заявителю
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 1 and SUBJ_ADMIN_REG not in subjects()
    assert len(tg) == 1 and 'Новая заявка пилота' in tg[0]
    assert_no_pii(tg, 'pilot@example.ru', 'Смирнов')


def test_pilot_email_match_then_select_existing_driver(client, tg, commit):
    driver = Driver.objects.create(first_name='Иван', last_name='Смирнов', slug='ivan-smirnov')
    with commit():
        client.post('/accounts/register/', PILOT_FORM)
    # до выбора: заявки нет, админ знает о регистрации, заявителю писем нет
    assert DriverClaim.objects.count() == 0
    assert subjects().count(SUBJ_ADMIN_REG) == 1 and mails('принята', 'pilot@example.ru') == []
    assert len(tg) == 1 and 'Новая регистрация пилота' in tg[0]
    with commit():
        client.post('/accounts/select-driver/', {'driver_id': driver.pk})
    claim = DriverClaim.objects.get()
    assert claim.driver == driver and claim.status == 'pending'
    assert len(mails('принята на рассмотрение', 'pilot@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 1
    assert len(tg) == 2 and 'Новая заявка пилота' in tg[1]
    assert_no_pii(tg, 'pilot@example.ru', 'Смирнов')


def test_pilot_email_match_then_choose_none(client, tg, commit):
    Driver.objects.create(first_name='Иван', last_name='Смирнов', slug='ivan-smirnov')
    with commit():
        client.post('/accounts/register/', PILOT_FORM)
    with commit():
        client.post('/accounts/select-driver/', {'driver_id': 'none'})
    claim = DriverClaim.objects.get()
    assert claim.driver is None and claim.requested_last_name == 'Смирнов'
    assert subjects().count(SUBJ_ADMIN_DRIVER) == 1 and len(tg) == 2


def test_pilot_email_duplicate_email_rejected(client, tg, commit, monkeypatch):
    from django.http import HttpResponse
    monkeypatch.setattr('accounts.views.render', lambda request, template, *a, **kw: HttpResponse(template))
    User.objects.create_user('x', 'pilot@example.ru', 'pass-12345')
    with commit():
        client.post('/accounts/register/', PILOT_FORM)
    assert DriverClaim.objects.count() == 0 and mail.outbox == [] and tg == []


# ===================== ПИЛОТ, подтверждение заявки =====================

def test_pilot_claim_approval_and_rejection_emails(client, tg, commit):
    with commit():
        client.post('/accounts/register/', PILOT_FORM)
    claim = DriverClaim.objects.get()
    driver = Driver.objects.create(first_name='Иван', last_name='Смирнов', slug='ivan-smirnov')
    mail.outbox.clear()
    claim.driver, claim.status = driver, 'approved'
    claim.save()
    claim.save()
    assert len(mails('подтверждена', 'pilot@example.ru')) == 1                 # ровно одно
    profile = claim.user.profile
    profile.refresh_from_db()
    assert 'pilot' in profile.roles and profile.verified and profile.driver == driver

    other = User.objects.create_user('o', 'other@example.ru', 'pass-12345')
    c2 = DriverClaim.objects.create(user=other, requested_first_name='Пётр', requested_last_name='Иванов')
    mail.outbox.clear()
    c2.status, c2.admin_comment = 'rejected', 'не подтвердили личность'
    c2.save()
    rej = mails('отклонена', 'other@example.ru')
    assert len(rej) == 1 and 'не подтвердили личность' in rej[0].body


# ===================== КОМАНДА, регистрация по email =====================

def _verify_link():
    letter = mails('Подтверждение регистрации команды', 'boss@example.ru')[0]
    url = re.search(r'https?://[^\s"<]+/teams/verify-email/[^\s"<]+', letter.body).group(0)
    return re.sub(r'^https?://[^/]+', '', url)  # путь без хоста (testserver)


def test_team_email_register_verify_no_match(client, tg, commit):
    with commit():
        client.post('/teams/register/', TEAM_FORM)
    assert User.objects.get(email='boss@example.ru').is_active is False
    assert len(mails('Подтверждение регистрации команды', 'boss@example.ru')) == 1
    assert TeamClaim.objects.count() == 0 and tg == []                          # до подтверждения заявки нет
    with commit():
        client.get(_verify_link())
    claim = TeamClaim.objects.get()
    assert claim.status == 'pending' and claim.team is None
    assert User.objects.get(email='boss@example.ru').is_active
    assert len(mails('принята на рассмотрение', 'boss@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_TEAM) == 1 and len(tg) == 1
    assert_no_pii(tg, 'boss@example.ru')


@pytest.mark.parametrize('choice', ['existing', 'none'])
def test_team_email_register_verify_match_then_select(client, tg, commit, choice):
    team = Team.objects.create(name='Kart Lab Racing')
    with commit():
        client.post('/teams/register/', TEAM_FORM)
        client.get(_verify_link())
    assert TeamClaim.objects.count() == 0                                        # нашли похожие — выбираем
    with commit():
        client.post('/teams/select-team/', {'team_id': team.pk if choice == 'existing' else 'none'})
    claim = TeamClaim.objects.get()
    assert (claim.team == team) if choice == 'existing' else (claim.team is None)
    assert len(mails('принята на рассмотрение', 'boss@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_TEAM) == 1 and len(tg) == 1


# ===================== КОМАНДА, подтверждение заявки =====================

def test_team_claim_approval_gives_manager_role_and_email(client, tg, commit):
    with commit():
        client.post('/teams/register/', TEAM_FORM)
        client.get(_verify_link())
    claim = TeamClaim.objects.get()
    team = Team.objects.create(name='Kart Lab')
    mail.outbox.clear()
    claim.team, claim.status = team, 'approved'
    claim.save()
    assert TeamManager.objects.filter(user=claim.user, team=team, is_active=True).exists()
    claim.user.profile.refresh_from_db()
    assert 'manager' in claim.user.profile.roles and claim.user.profile.team == team
    assert len(mails('подтверждена', 'boss@example.ru')) == 1


def test_team_claim_rejection_email(client, tg, commit):
    with commit():
        client.post('/teams/register/', TEAM_FORM)
        client.get(_verify_link())
    claim = TeamClaim.objects.get()
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
    assert len(mails('принята на рассмотрение', 'ya@example.ru')) == 1
    assert subjects().count(SUBJ_ADMIN_TEAM) == 1 and len(tg) == 1
    assert_no_pii(tg, 'ya@example.ru')


def test_yandex_team_new_team_saves_city_and_notifies(client, social_user, tg, commit):
    client.force_login(social_user)
    with commit():
        client.post('/accounts/yandex/onboarding/team/', {'action': 'new', 'team_name': 'Fresh', 'city': 'Казань'})
    claim = TeamClaim.objects.get()
    assert claim.team.name == 'Fresh' and claim.team.city == 'Казань'
    assert TeamManager.objects.filter(user=social_user, team=claim.team).exists()  # создатель — менеджер сразу
    assert subjects().count(SUBJ_ADMIN_TEAM) == 1 and len(tg) == 1


def test_yandex_team_preselected_name_and_id(client, social_user, tg, commit):
    client.force_login(social_user)
    session = client.session
    session['yandex_preselected_team_name'] = 'Preselected'
    session.save()
    with commit():
        client.get('/accounts/yandex/onboarding/team/')
    assert TeamClaim.objects.get().team.name == 'Preselected'
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


# ===================== Организатор: отдельный флоу =====================

def test_organizer_register_sends_only_verification_mail(client, tg, commit, monkeypatch):
    from django.http import HttpResponse
    monkeypatch.setattr('organizers.views.render', lambda request, template, *a, **kw: HttpResponse(template))
    with commit():
        client.post('/organizers/register/', {
            'email': 'org@example.ru', 'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
            'first_name': 'Олег', 'last_name': 'Клубов', 'phone': '+79990000000', 'telegram': '@club',
        })
    assert User.objects.get(email='org@example.ru').is_active is False
    assert len(mails('Подтверждение', 'org@example.ru')) == 1
    assert DriverClaim.objects.count() == 0 and TeamClaim.objects.count() == 0 and tg == []
