"""Уведомление админ-чата о новом обращении по ПД."""
import pytest

from website.feedback import notify, tg_sync
from website.models import DataRequest, FeedbackBotSettings

FERNET = 'cmV6b2x2ZXpvbHZlenJlem9sdmV6b2x2ZXpvbHZlenI='
TOKEN = '123456789:AAFabcdefghijklmnopqrstuvwxyz0123'


@pytest.fixture
def configured(db, settings):
    settings.FEEDBACK_FERNET_KEY = FERNET
    cfg = FeedbackBotSettings.get()
    cfg.set_token(TOKEN)
    cfg.admin_chat_id = -1001
    cfg.save()


@pytest.fixture
def request_obj(db):
    return DataRequest.objects.create(
        request_type='deletion', contact='secret@example.com', text='мои данные: паспорт 1234', is_confirmed=True,
    )


def test_message_has_type_deadline_link_but_no_personal_data(request_obj):
    text = notify.data_request_text(request_obj)
    assert 'Удаление данных' in text and f'datarequest/edit/{request_obj.pk}/' in text
    assert f'{request_obj.due_date:%d.%m.%Y}' in text
    assert 'secret@example.com' not in text and 'паспорт' not in text


def test_sends_to_admin_chat(configured, request_obj, monkeypatch):
    calls = []
    monkeypatch.setattr(tg_sync, 'api_call', lambda token, method, proxy=None, payload=None, timeout=0: calls.append((token, method, payload, timeout)) or {})
    assert notify.send_admin_chat_message(notify.data_request_text(request_obj)) is True
    token, method, payload, timeout = calls[0]
    assert method == 'sendMessage' and payload['chat_id'] == -1001 and payload['parse_mode'] == 'HTML'
    assert token == TOKEN and timeout == notify.SEND_TIMEOUT


def test_noop_when_not_configured(db, request_obj, monkeypatch):
    monkeypatch.setattr(tg_sync, 'api_call', lambda *a, **k: pytest.fail('не должно вызываться'))
    assert notify.send_admin_chat_message('x') is False


def test_failure_is_swallowed_and_token_not_logged(configured, monkeypatch, caplog):
    def boom(*a, **k):
        raise tg_sync.TelegramApiError('Нет соединения с Telegram: таймаут')
    monkeypatch.setattr(tg_sync, 'api_call', boom)
    with caplog.at_level('WARNING', logger='feedback'):
        assert notify.send_admin_chat_message('x') is False
    assert TOKEN not in caplog.text


def test_form_submit_triggers_notification(client, db, monkeypatch):
    sent = []
    monkeypatch.setattr('website.legal_views.notify_data_request', lambda obj: sent.append(obj.pk))
    resp = client.post('/legal/data-request/', {
        'request_type': 'deletion', 'page_url': '', 'contact': 'a@example.com',
        'text': 'удалите мои данные, пожалуйста', 'confirm': 'on',
    })
    assert resp.status_code == 302 and len(sent) == 1


def test_notify_data_request_sends_in_background_without_db_in_thread(configured, request_obj, monkeypatch):
    import threading
    done = threading.Event()
    calls = []

    def fake(token, method, proxy=None, payload=None, timeout=0):
        calls.append((method, payload['text']))
        done.set()
        return {}
    monkeypatch.setattr(tg_sync, 'api_call', fake)
    notify.notify_data_request(request_obj)
    assert done.wait(5) and calls[0][0] == 'sendMessage' and f'№{request_obj.pk}' in calls[0][1]


def test_notify_data_request_noop_when_not_configured(db, request_obj, monkeypatch):
    monkeypatch.setattr(tg_sync, 'api_call', lambda *a, **k: pytest.fail('не должно вызываться'))
    notify.notify_data_request(request_obj)  # не бросает и ничего не шлёт
