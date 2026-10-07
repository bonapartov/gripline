"""Уведомления по заявкам пилотов и команд: админу (письмо + Telegram) и заявителю."""
import pytest
from django.contrib.auth.models import User
from django.core import mail

from accounts.models import DriverClaim
from teams.models import TeamClaim, TeamManager
from website import claim_notify
from website.models import Driver, Team

ADMIN_SUBJECTS = ('[Gripline] Новая заявка на управление пилотом', '[Gripline] Новая заявка от команды')


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.BASE_URL = 'https://gripline.ru'


@pytest.fixture
def chat(monkeypatch):
    """Перехватывает сообщения в админ-чат."""
    sent = []
    monkeypatch.setattr('website.feedback.notify.notify_admin_chat', lambda text, label: sent.append((text, label)))
    return sent


@pytest.fixture
def user(db):
    return User.objects.create_user('ivan', 'ivan@example.ru', 'pass-12345')


def to_admin():
    return [m for m in mail.outbox if m.subject in ADMIN_SUBJECTS]


def to_user(subject_part):
    return [m for m in mail.outbox if m.to == ['ivan@example.ru'] and subject_part in m.subject]


# ---------- админу ----------

def test_driver_claim_notifies_admin_once(user, chat, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        claim = DriverClaim.objects.create(
            user=user, requested_first_name='Иван', requested_last_name='Смирнов', requested_city='Казань')
    letters = to_admin()
    assert len(letters) == 1
    assert letters[0].subject == '[Gripline] Новая заявка на управление пилотом'
    assert f'https://gripline.ru/admin/accounts/driverclaim/edit/{claim.pk}/' in letters[0].body
    assert 'ivan@example.ru' in letters[0].body and 'Казань' in letters[0].body
    assert len(chat) == 1


def test_resaving_claim_does_not_notify_again(user, chat, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        claim = DriverClaim.objects.create(user=user, requested_first_name='Иван', requested_last_name='Смирнов')
        claim.admin_comment = 'проверяю'
        claim.save()
    assert len(to_admin()) == 1 and len(chat) == 1


def test_approved_claim_created_by_script_does_not_notify_admin(user, chat, django_capture_on_commit_callbacks):
    # demo/create_test_users создают сразу подтверждённые заявки — админа не будить
    with django_capture_on_commit_callbacks(execute=True):
        DriverClaim.objects.create(user=user, requested_first_name='Иван', requested_last_name='Смирнов',
                                   status='approved')
    assert to_admin() == [] and chat == []


def test_not_sent_when_transaction_rolls_back(user, chat, django_capture_on_commit_callbacks):
    from django.db import transaction
    with django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                DriverClaim.objects.create(user=user, requested_first_name='Иван', requested_last_name='Смирнов')
                raise RuntimeError
        except RuntimeError:
            pass
    assert to_admin() == [] and chat == []


def test_team_claim_notifies_admin_once(user, chat, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        claim = TeamClaim.objects.create(user=user, requested_team_name='Kart Lab')
    letters = to_admin()
    assert len(letters) == 1 and letters[0].subject == '[Gripline] Новая заявка от команды'
    assert f'/admin/teams/teamclaim/edit/{claim.pk}/' in letters[0].body
    assert len(chat) == 1


def test_telegram_text_has_link_but_no_personal_data(user, chat, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        driver = Driver.objects.create(first_name='Пётр', last_name='Секретов', slug='petr-sekretov')
        claim = DriverClaim.objects.create(
            user=user, driver=driver, requested_first_name='Пётр', requested_last_name='Секретов')
    text = chat[0][0]
    assert f'№{claim.pk}' in text and f'/admin/accounts/driverclaim/edit/{claim.pk}/' in text
    for private in ('ivan@example.ru', 'Пётр', 'Секретов'):
        assert private not in text


def test_telegram_text_for_team_names_the_team_and_escapes_html(user, chat, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        TeamClaim.objects.create(user=user, requested_team_name='<b>Kart</b> Lab')
    text = chat[0][0]
    assert '&lt;b&gt;Kart&lt;/b&gt; Lab' in text and '<b>Kart</b>' not in text
    assert 'ivan@example.ru' not in text


def test_mail_failure_does_not_block_telegram(user, chat, monkeypatch, django_capture_on_commit_callbacks):
    def boom(*a, **kw):
        raise OSError('smtp down')
    monkeypatch.setattr(claim_notify, 'send_templated_mail', boom)
    with django_capture_on_commit_callbacks(execute=True):
        DriverClaim.objects.create(user=user, requested_first_name='Иван', requested_last_name='Смирнов')
    assert len(chat) == 1


# ---------- все пути создания заявки ----------

REGISTER = {
    'username': 'newbie', 'email': 'new@example.ru', 'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
    'first_name': 'Иван', 'last_name': 'Смирнов', 'city': 'Казань',
}


def test_register_new_pilot_path_notifies_admin_once(db, client, chat, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        client.post('/accounts/register/', REGISTER)
    assert DriverClaim.objects.filter(user__email='new@example.ru').count() == 1
    assert len(to_admin()) == 1 and len(chat) == 1


def test_select_driver_path_notifies_admin_once(db, client, chat, django_capture_on_commit_callbacks):
    driver = Driver.objects.create(first_name='Иван', last_name='Смирнов', slug='ivan-smirnov', city='Казань')
    with django_capture_on_commit_callbacks(execute=True):
        client.post('/accounts/register/', REGISTER)
    assert to_admin() == []  # пока пилот не выбран — заявки нет
    with django_capture_on_commit_callbacks(execute=True):
        client.post('/accounts/select-driver/', {'driver_id': driver.pk})
    claim = DriverClaim.objects.get(user__email='new@example.ru')
    assert claim.driver == driver and len(to_admin()) == 1 and len(chat) == 1


def test_select_team_path_notifies_admin_once(client, user, chat, django_capture_on_commit_callbacks):
    team = Team.objects.create(name='Kart Lab')
    session = client.session
    session.update({'found_teams': [{'id': team.pk, 'name': team.name}], 'user_id': user.pk,
                    'requested_team_name': 'Kart Lab'})
    session.save()
    with django_capture_on_commit_callbacks(execute=True):
        client.post('/teams/select-team/', {'team_id': team.pk})
    assert TeamClaim.objects.filter(user=user, team=team).count() == 1
    assert len(to_admin()) == 1 and len(chat) == 1


# ---------- заявителю (команда) ----------

def test_team_claim_pending_email_to_applicant(user, chat, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        TeamClaim.objects.create(user=user, requested_team_name='Kart Lab')
    letters = to_user('принята на рассмотрение')
    assert len(letters) == 1 and 'Kart Lab' in letters[0].body
    assert 'https://gripline.ru/teams/dashboard/' in letters[0].body


def test_team_claim_approval_creates_manager_and_sends_email_once(user, chat):
    team = Team.objects.create(name='Kart Lab')
    claim = TeamClaim.objects.create(user=user, requested_team_name='Kart Lab')
    mail.outbox.clear()
    claim.team, claim.status = team, 'approved'
    claim.save()
    claim.save()  # повторное сохранение письма не шлёт
    assert TeamManager.objects.filter(user=user, team=team, is_active=True).exists()
    letters = to_user('подтверждена')
    assert len(letters) == 1 and 'Kart Lab' in letters[0].body
    assert 'https://gripline.ru/teams/dashboard/' in letters[0].body


def test_team_claim_approved_without_team_sends_nothing_until_team_chosen(user, chat):
    claim = TeamClaim.objects.create(user=user, requested_team_name='Kart Lab')
    mail.outbox.clear()
    claim.status = 'approved'
    claim.save()
    assert to_user('подтверждена') == [] and not TeamManager.objects.filter(user=user).exists()
    claim.team = Team.objects.create(name='Kart Lab')
    claim.save()
    assert len(to_user('подтверждена')) == 1 and TeamManager.objects.filter(user=user).exists()


def test_team_claim_rejection_email_carries_reason_once(user, chat):
    claim = TeamClaim.objects.create(user=user, requested_team_name='Kart Lab')
    mail.outbox.clear()
    claim.status, claim.admin_comment = 'rejected', 'команда уже закреплена'
    claim.save()
    claim.save()
    letters = to_user('отклонена')
    assert len(letters) == 1 and 'команда уже закреплена' in letters[0].body
    assert not TeamManager.objects.filter(user=user).exists()


def test_team_claim_emails_skip_user_without_email(chat, db):
    tg_user = User.objects.create_user('tg_1')  # вход через Telegram — e-mail пуст
    claim = TeamClaim.objects.create(user=tg_user, requested_team_name='Kart Lab')
    claim.status = 'rejected'
    claim.save()
    assert [m for m in mail.outbox if m.to == ['']] == []
