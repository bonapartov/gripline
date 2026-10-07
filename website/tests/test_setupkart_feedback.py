"""Обратная связь из приложения GripLine SetupKart (ТЗ приложения §6.14, §13.2)."""
import asyncio

import pytest
from django.core import mail
from django.core.cache import cache

from website.feedback import service, tg_sync
from website.feedback.channels.base import DeliveryError
from website.feedback.channels.telegram import TelegramAdapter, _card_sync
from website.models import APP_FEEDBACK_CATEGORY_SLUG, Feedback, FeedbackBotSettings, FeedbackCategory
from website.setupkart import feedback as app_feedback

FERNET = 'cmV6b2x2ZXpvbHZlenJlem9sdmV6b2x2ZXpvbHZlenI='
TOKEN = '123456789:AAFabcdefghijklmnopqrstuvwxyz0123'
URL = '/api/setupkart/feedback/'


@pytest.fixture(autouse=True)
def env(db, settings, monkeypatch):
    cache.clear()
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
    monkeypatch.setattr(app_feedback.threading, 'Thread', SyncThread)
    calls = []

    def fake_api(token, method, proxy=None, payload=None, timeout=0):
        calls.append((method, payload))
        return {'message_id': 777}
    monkeypatch.setattr(tg_sync, 'api_call', fake_api)
    yield calls
    cache.clear()


def post(client, **body):
    data = {'client_id': 'install-1', 'category': 'bug', 'text': 'Не сохраняется давление', 'app_version': '0.3',
            'device_info': 'Android 14, Pixel 7', **body}
    return client.post(URL, data, content_type='application/json')


def test_feedback_creates_ticket_card_and_email(client, env, django_capture_on_commit_callbacks):
    cat = app_feedback.app_category()
    cat.admin_topic_id = 55
    cat.save()
    with django_capture_on_commit_callbacks(execute=True):
        r = post(client, contact_email='pilot@example.ru', consent=True)
    assert r.status_code == 201
    fb = Feedback.objects.get(pk=r.json()['number'])
    assert fb.user.channel == 'setupkart' and fb.category.slug == APP_FEEDBACK_CATEGORY_SLUG
    assert fb.answers['Тип'] == 'Ошибка' and fb.answers['Сообщение'] == 'Не сохраняется давление'
    assert 'pilot@example.ru' in fb.admin_note

    # карточка — в тему категории, без e-mail и без кнопки «Ответить»
    method, payload = env[0]
    assert method == 'sendMessage' and payload['message_thread_id'] == 55 and payload['chat_id'] == -1001
    assert 'pilot@example.ru' not in payload['text']
    buttons = [b['text'] for row in payload['reply_markup']['inline_keyboard'] for b in row]
    assert 'Ответить' not in buttons and 'В работу' in buttons
    fb.refresh_from_db()
    assert fb.admin_chat_message_id == 777 and fb.admin_thread_id == 55

    # письмо администратору с e-mail для ответа
    letter = mail.outbox[-1]
    assert letter.subject == '[GripLine SetupKart] Обратная связь: Ошибка'
    assert 'pilot@example.ru' in letter.body and 'Не сохраняется давление' in letter.body


def test_without_email_says_no_reply_possible(client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        assert post(client).status_code == 201
    fb = Feedback.objects.get()
    assert 'ответить нельзя' in fb.admin_note
    assert 'не указан' in mail.outbox[-1].body


@pytest.mark.parametrize('body, code', [
    (dict(category='spam'), 'invalid'),
    (dict(text='   '), 'invalid'),
    (dict(text='x' * 5001), 'invalid'),
    (dict(client_id=''), 'invalid'),
    (dict(contact_email='not-an-email', consent=True), 'invalid_email'),
    (dict(contact_email='pilot@example.ru'), 'consent_required'),
])
def test_validation(client, body, code):
    r = post(client, **body)
    assert r.status_code == 400 and r.json()['error'] == code
    assert Feedback.objects.count() == 0


def test_rate_limit_per_ip(client):
    codes = [post(client, client_id=f'c{i}').status_code for i in range(11)]
    assert codes[-1] == 429 and 429 not in codes[:10]


def test_banned_install_rejected(client):
    user = service.get_or_create_user('setupkart', 'install-1')
    user.is_banned = True
    user.save()
    assert post(client).status_code == 429


def test_app_category_not_in_bot_menu_but_gets_topic(env, monkeypatch):
    cat = app_feedback.app_category()
    assert cat.slug == APP_FEEDBACK_CATEGORY_SLUG and not cat.is_active
    assert cat not in list(service.active_categories())
    env.clear()

    def fake_topic(token, method, proxy=None, payload=None, timeout=0):
        env.append((method, payload))
        return {'message_thread_id': 99}
    import website.feedback.tg_sync as ts
    monkeypatch.setattr(ts, 'api_call', fake_topic)
    created, errors = ts.create_category_topics(FeedbackBotSettings.get())
    cat.refresh_from_db()
    assert cat.admin_topic_id == 99 and errors == []


def test_bot_cannot_message_app_user():
    user = service.get_or_create_user('setupkart', 'install-1')
    adapter = TelegramAdapter(bot=object())
    with pytest.raises(DeliveryError):
        asyncio.run(adapter.send_message(user, 'ответ модератора'))


def test_card_for_telegram_user_still_has_reply_button():
    cat = FeedbackCategory.objects.create(slug='error', title='Ошибка в данных')
    tg_user = service.get_or_create_user('telegram', '12345', username='pilot')
    fb = Feedback.objects.create(user=tg_user, category=cat, answers={'text': 'x'})
    _, rows = _card_sync(fb.pk)
    assert any(label == 'Ответить' for row in rows for label, _ in row)
