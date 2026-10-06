"""Обработчики Telegram-бота на фейковой сессии (без сети)."""
import asyncio
import datetime

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery, DeleteMessage, EditMessageText, GetFile, GetMe, GetUpdates, SendDocument,
    SendMessage, SetMessageReaction,
)
from aiogram.types import CallbackQuery, Chat, File, Message, Update, User

from website.feedback import service, sources
from website.feedback import telegram_bot
from website.models import (
    Feedback, FeedbackBotSettings, FeedbackCategory, FeedbackModerator,
    FeedbackStep, FeedbackUser,
)
from website.tests.test_feedback_service import PNG

TOKEN = '123456789:AAFabcdefghijklmnopqrstuvwxyz0123'
ADMIN_CHAT = -1001234567890
NOW = datetime.datetime(2026, 10, 6, 12, 0, tzinfo=datetime.timezone.utc)


class FakeSession(BaseSession):
    """Запоминает вызовы Bot API и отвечает правдоподобными заглушками."""

    def __init__(self):
        super().__init__()
        self.calls = []
        self._id = 1000

    async def close(self):
        pass

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield PNG

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, SendDocument, EditMessageText)):
            self._id += 1
            return Message(message_id=getattr(method, 'message_id', None) or self._id, date=NOW,
                           chat=Chat(id=method.chat_id, type='private'))
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name='bot', username='gripline_support_bot')
        if isinstance(method, GetUpdates):
            await asyncio.sleep(0.05)  # long polling без апдейтов
            return []
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id='u', file_path='photos/a.png')
        return True

    def sent(self, kind=SendMessage):
        return [c for c in self.calls if isinstance(c, kind)]

    def texts_to(self, chat_id):
        return [c.text for c in self.sent() if c.chat_id == chat_id]


@pytest.fixture
def env(settings, tmp_path, monkeypatch, transactional_db):
    settings.FEEDBACK_FERNET_KEY = 'cmV6b2x2ZXpvbHZlenJlem9sdmV6b2x2ZXpvbHZlenI='
    settings.PRIVATE_MEDIA_ROOT = tmp_path / 'private'
    session = FakeSession()
    monkeypatch.setattr(telegram_bot, 'build_bot', lambda token, proxy=None: Bot(TOKEN, session=session))
    cfg = FeedbackBotSettings.get()
    cfg.admin_chat_id = ADMIN_CHAT
    cfg.privacy_policy_url = 'https://example.org/privacy'
    cfg.save()
    service.ensure_texts()
    cat = FeedbackCategory.objects.create(slug='err', title='Ошибка', emoji='🐞', deep_link_code='err', admin_topic_id=77)
    FeedbackStep.objects.create(category=cat, sort_order=1, key='where', prompt_text='Где ошибка? Укажите.', skip_if_source_set=True)
    FeedbackStep.objects.create(category=cat, sort_order=2, key='what', prompt_text='Что не так?')
    FeedbackStep.objects.create(category=cat, sort_order=3, key='shot', prompt_text='Скриншот', type='attachment',
                                is_required=False, skip_button_text='Пропустить')
    FeedbackModerator.objects.create(external_user_id='900', name='Модератор Иван')
    app = telegram_bot.FeedbackTelegramBot(TOKEN, None)
    return type('Env', (), {'app': app, 'session': session, 'cat': cat})


def tg_user(uid=111, username='vasya'):
    return User(id=uid, is_bot=False, first_name='Вася', username=username)


def msg(uid, text=None, chat_id=None, chat_type='private', reply_to=None, thread=None, **extra):
    chat_id = chat_id if chat_id is not None else uid
    return Update(update_id=1, message=Message(
        message_id=extra.pop('message_id', 5000), date=NOW, chat=Chat(id=chat_id, type=chat_type),
        from_user=tg_user(uid), text=text, reply_to_message=reply_to, **extra,
    ))


def press(uid, data, chat_id=None, message_id=1):
    chat_id = chat_id if chat_id is not None else uid
    chat_type = 'private' if chat_id == uid else 'supergroup'
    return Update(update_id=2, callback_query=CallbackQuery(
        id='cb', from_user=tg_user(uid), chat_instance='x', data=data,
        message=Message(message_id=message_id, date=NOW, chat=Chat(id=chat_id, type=chat_type)),
    ))


def feed(env, update):
    asyncio.run(env.app.dp.feed_update(env.app.bot, update))


def complete_flow(env, uid=111):
    feed(env, msg(uid, '/start'))
    feed(env, press(uid, f'cat:{env.cat.pk}'))
    feed(env, msg(uid, 'Страница рейтинга'))
    feed(env, msg(uid, 'Неверное место <b>1</b>'))
    feed(env, press(uid, 'skip'))
    return Feedback.objects.latest('id')


def test_start_shows_privacy_once_and_menu(env):
    feed(env, msg(111, '/start'))
    texts = env.session.texts_to(111)
    assert 'https://example.org/privacy' in texts[0]
    assert 'Привет' in texts[1]
    buttons = env.session.sent()[-1].reply_markup.inline_keyboard
    assert buttons[0][0].callback_data == f'cat:{env.cat.pk}'
    feed(env, msg(111, '/start'))
    assert sum('https://example.org/privacy' in t for t in env.session.texts_to(111)) == 1


def test_full_flow_creates_card_in_category_topic(env):
    fb = complete_flow(env)
    assert fb.answers['what'] == 'Неверное место <b>1</b>'
    assert 'принято' in env.session.texts_to(111)[-1] and f'№{fb.pk}' in env.session.texts_to(111)[-1]
    card = [c for c in env.session.sent() if c.chat_id == ADMIN_CHAT][0]
    assert card.message_thread_id == 77
    assert card.parse_mode == 'HTML'
    # пользовательский текст экранирован, разметку не сломать
    assert '&lt;b&gt;1&lt;/b&gt;' in card.text and '<b>1</b>' not in card.text
    assert [b.callback_data for b in card.reply_markup.inline_keyboard[0]] == [f'fb:{fb.pk}:work', f'fb:{fb.pk}:reply', f'fb:{fb.pk}:done']
    fb.refresh_from_db()
    assert fb.admin_chat_message_id and fb.admin_thread_id == 77


def test_attachment_downloaded_and_card_gets_document(env):
    feed(env, msg(111, '/start'))
    feed(env, press(111, f'cat:{env.cat.pk}'))
    feed(env, msg(111, 'где'))
    feed(env, msg(111, 'что'))
    feed(env, msg(111, document={'file_id': 'F1', 'file_unique_id': 'u', 'file_name': 'шот.png', 'file_size': len(PNG)}))
    feed(env, press(111, 'done'))
    fb = Feedback.objects.get()
    assert fb.attachments.count() == 1
    docs = env.session.sent(SendDocument)
    assert docs and docs[0].chat_id == ADMIN_CHAT


def test_oversized_file_rejected_without_download(env):
    feed(env, msg(111, '/start'))
    feed(env, press(111, f'cat:{env.cat.pk}'))
    feed(env, msg(111, 'где'))
    feed(env, msg(111, 'что'))
    feed(env, msg(111, document={'file_id': 'F1', 'file_unique_id': 'u', 'file_name': 'big.pdf', 'file_size': 50 * 1024 * 1024}))
    assert not env.session.sent(SendDocument)
    assert not [c for c in env.session.calls if isinstance(c, GetFile)]
    assert 'не подходит' in env.session.texts_to(111)[-1]


def test_deep_link_skips_where_step(env, monkeypatch):
    monkeypatch.setattr(sources, 'resolve', lambda kind, pk: sources.ResolvedSource(kind, pk, 'Этап 5', 'https://x/e/'))
    feed(env, msg(111, '/start err_s_142'))
    assert 'Что не так' in env.session.texts_to(111)[-1]
    draft = service.get_draft(FeedbackUser.objects.get(external_user_id='111'))
    assert (draft.source_kind, draft.source_id) == ('stage', 142)


def test_broken_deep_link_falls_back_to_menu(env):
    feed(env, msg(111, '/start err_s_999999'))  # такого этапа нет
    assert 'Привет' in env.session.texts_to(111)[-1]
    feed(env, msg(112, '/start мусор'))
    assert 'Привет' in env.session.texts_to(112)[-1]


def test_cancel(env):
    feed(env, msg(111, '/start'))
    feed(env, press(111, f'cat:{env.cat.pk}'))
    feed(env, msg(111, '/cancel'))
    assert not service.get_draft(FeedbackUser.objects.get(external_user_id='111'))
    assert 'Отменено' in env.session.texts_to(111)[-1]


def test_banned_user_gets_no_answer(env):
    user = service.get_or_create_user('telegram', 111, 'vasya', 'Вася')
    service.set_banned(user, True)
    feed(env, msg(111, '/start'))
    feed(env, msg(111, 'привет'))
    assert not env.session.sent()


def test_moderator_button_changes_status_and_notifies(env):
    fb = complete_flow(env)
    env.session.calls.clear()
    feed(env, press(900, f'fb:{fb.pk}:work', chat_id=ADMIN_CHAT))
    fb.refresh_from_db()
    assert fb.status == 'in_work' and fb.assigned_to.name == 'Модератор Иван'
    assert any('взято в работу' in t for t in env.session.texts_to(111))
    edits = env.session.sent(EditMessageText)
    assert edits and 'В работе: Модератор Иван' in edits[0].text
    feed(env, press(900, f'fb:{fb.pk}:done', chat_id=ADMIN_CHAT))
    fb.refresh_from_db()
    assert fb.status == 'done' and any('закрыто' in t for t in env.session.texts_to(111))


def test_repeated_press_does_not_notify_twice(env):
    fb = complete_flow(env)
    feed(env, press(900, f'fb:{fb.pk}:work', chat_id=ADMIN_CHAT))
    env.session.calls.clear()
    feed(env, press(900, f'fb:{fb.pk}:work', chat_id=ADMIN_CHAT))
    assert not env.session.texts_to(111)


def test_non_moderator_press_does_nothing(env):
    fb = complete_flow(env)
    feed(env, press(555, f'fb:{fb.pk}:done', chat_id=ADMIN_CHAT))
    fb.refresh_from_db()
    assert fb.status == 'new'
    # и в чужом чате кнопка тоже не работает, даже у модератора
    feed(env, press(900, f'fb:{fb.pk}:done', chat_id=900))
    fb.refresh_from_db()
    assert fb.status == 'new'


def card_message(fb):
    return Message(message_id=fb.admin_chat_message_id, date=NOW, chat=Chat(id=ADMIN_CHAT, type='supergroup'))


def test_moderator_reply_delivered_and_logged(env):
    fb = complete_flow(env)
    env.session.calls.clear()
    feed(env, msg(900, 'Исправили, спасибо!', chat_id=ADMIN_CHAT, chat_type='supergroup',
                  reply_to=card_message(fb), message_id=7000))
    out = fb.messages.get()
    assert out.direction == 'out' and out.delivered and out.moderator.name == 'Модератор Иван'
    delivered = env.session.texts_to(111)[-1]
    assert 'Исправили, спасибо!' in delivered and f'№{fb.pk}' in delivered
    assert env.session.sent(SetMessageReaction)


def test_reply_from_non_moderator_ignored(env):
    fb = complete_flow(env)
    env.session.calls.clear()
    feed(env, msg(555, 'я не модератор', chat_id=ADMIN_CHAT, chat_type='supergroup', reply_to=card_message(fb)))
    assert not fb.messages.exists() and not env.session.texts_to(111)


def test_ban_command_in_admin_chat(env):
    fb = complete_flow(env)
    feed(env, msg(900, '/ban спам', chat_id=ADMIN_CHAT, chat_type='supergroup', reply_to=card_message(fb)))
    user = FeedbackUser.objects.get(external_user_id='111')
    assert user.is_banned and user.ban_reason == 'спам'
    env.session.calls.clear()
    feed(env, msg(111, '/start'))
    assert not env.session.sent()


def test_ban_by_non_moderator_ignored(env):
    fb = complete_flow(env)
    feed(env, msg(555, '/ban', chat_id=ADMIN_CHAT, chat_type='supergroup', reply_to=card_message(fb)))
    assert not FeedbackUser.objects.get(external_user_id='111').is_banned


def test_dialog_message_goes_to_same_topic(env):
    fb = complete_flow(env)
    env.session.calls.clear()
    feed(env, msg(111, 'Ещё уточнение'))
    forwarded = [c for c in env.session.sent() if c.chat_id == ADMIN_CHAT][0]
    assert 'Ещё уточнение' in forwarded.text
    assert forwarded.message_thread_id == fb.admin_thread_id
    assert forwarded.reply_to_message_id == fb.admin_chat_message_id
    assert fb.messages.get().direction == 'in'
    # reply модератора на это сообщение тоже находит обращение
    sent_id = fb.messages.get().admin_chat_message_id
    assert service.find_feedback_by_admin_message(sent_id) == fb


def test_dialog_closed_feedback_offers_new(env):
    fb = complete_flow(env)
    service.change_status(fb, 'done')
    env.session.calls.clear()
    feed(env, msg(111, 'а ещё...'))
    assert not [c for c in env.session.sent() if c.chat_id == ADMIN_CHAT]
    assert 'закрыто' in env.session.texts_to(111)[-1]


def test_forget_removes_data_and_edits_card(env):
    fb = complete_flow(env)
    env.session.calls.clear()
    feed(env, msg(111, '/forget'))
    assert 'Удалить' in env.session.texts_to(111)[-1]
    feed(env, press(111, 'forget:yes'))
    fb.refresh_from_db()
    assert fb.user is None and fb.answers == {} and fb.anonymized_at
    assert not FeedbackUser.objects.filter(external_user_id='111').exists()
    edits = env.session.sent(EditMessageText)
    assert edits and 'Данные удалены по запросу пользователя' in edits[-1].text
    assert edits[-1].reply_markup is None


def test_rate_limit_message(env):
    cfg = FeedbackBotSettings.get()
    cfg.rate_limit_per_hour = 1
    cfg.save()
    complete_flow(env)
    feed(env, press(111, f'cat:{env.cat.pk}'))
    feed(env, msg(111, 'a'))
    feed(env, msg(111, 'b'))
    feed(env, press(111, 'skip'))
    assert 'слишком много' in env.session.texts_to(111)[-1]
    assert Feedback.objects.count() == 1


def test_text_edit_applies_without_restart(env):
    from website.models import FeedbackText
    FeedbackText.objects.filter(key='welcome').update(text='Новое приветствие')
    feed(env, msg(111, '/start'))
    assert env.session.texts_to(111)[-1] == 'Новое приветствие'


def test_id_command(env):
    feed(env, msg(321, '/id'))
    assert '321' in env.session.texts_to(321)[-1]


def test_restart_snapshot_changes(env):
    snap = telegram_bot.load_snapshot()
    cfg = FeedbackBotSettings.get()
    from django.utils import timezone
    cfg.restart_requested_at = timezone.now()
    cfg.save()
    assert telegram_bot.load_snapshot() != snap
    cfg.set_token(TOKEN)
    cfg.save()
    s2 = telegram_bot.load_snapshot()
    cfg.set_token('999999:AAFzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz')
    cfg.save()
    assert telegram_bot.load_snapshot() != s2


def test_log_filter_redacts_token():
    import logging
    rec = logging.LogRecord('feedback', logging.ERROR, 'f', 1, f'POST https://api.telegram.org/bot{TOKEN}/getMe failed', (), None)
    telegram_bot.TokenRedactFilter(TOKEN).filter(rec)
    assert TOKEN not in rec.getMessage() and '***' in rec.getMessage()


def test_card_contains_source_title_and_link(env, monkeypatch):
    monkeypatch.setattr(sources, 'resolve', lambda kind, pk: sources.ResolvedSource(kind, pk, 'Этап 5 <РМ Мини>', 'https://gripline.ru/e/5/'))
    feed(env, msg(111, '/start err_s_142'))
    feed(env, msg(111, 'что не так'))
    feed(env, press(111, 'skip'))
    card = [c for c in env.session.sent() if c.chat_id == ADMIN_CHAT][0]
    assert 'Этап «Этап 5 &lt;РМ Мини&gt;»' in card.text
    assert '<a href="https://gripline.ru/e/5/">' in card.text
    fb = Feedback.objects.get()
    assert (fb.source_kind, fb.source_id) == ('stage', 142)


def test_plain_start_code_opens_category_without_source(env):
    feed(env, msg(111, '/start err'))
    assert 'Где ошибка' in env.session.texts_to(111)[-1]
    assert service.get_draft(FeedbackUser.objects.get(external_user_id='111')).source_kind == ''


def test_supervisor_polls_and_exits_when_settings_change(env, monkeypatch):
    """_run_session поднимает polling на фейковой сессии и сам завершается,
    когда load_snapshot() начинает отличаться от исходного."""
    snap = telegram_bot.Snapshot(enabled=True, token=TOKEN, proxy=None, restart_at=None, refresh_sec=0.1)
    calls = {'n': 0}

    def changing():
        calls['n'] += 1
        return snap if calls['n'] < 3 else telegram_bot.Snapshot(True, TOKEN, None, 'restart-now', 0.1)
    monkeypatch.setattr(telegram_bot, 'load_snapshot', changing)

    async def run():
        await asyncio.wait_for(telegram_bot._run_session(snap, asyncio.Event()), timeout=10)
    asyncio.run(run())
    assert calls['n'] >= 3
    assert [c for c in env.session.calls if isinstance(c, GetUpdates)]


def test_supervisor_stops_on_signal_event(env):
    snap = telegram_bot.Snapshot(enabled=True, token=TOKEN, proxy=None, restart_at=None, refresh_sec=60)

    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(telegram_bot._run_session(snap, stop))
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(task, timeout=10)
    asyncio.run(run())


def anonymous_admin_msg(text, reply_to, chat_id=ADMIN_CHAT, sender_chat_id=ADMIN_CHAT):
    """Сообщение администратора, отправленное «от имени группы»."""
    return Update(update_id=3, message=Message(
        message_id=7100, date=NOW, chat=Chat(id=chat_id, type='supergroup'),
        from_user=User(id=telegram_bot.ANONYMOUS_ADMIN_ID, is_bot=True, first_name='Group', username='GroupAnonymousBot'),
        sender_chat=Chat(id=sender_chat_id, type='supergroup'), text=text, reply_to_message=reply_to,
    ))


def test_anonymous_admin_reply_is_delivered(env):
    fb = complete_flow(env)
    env.session.calls.clear()
    feed(env, anonymous_admin_msg('Ответ от анонимного админа', card_message(fb)))
    out = fb.messages.get()
    assert out.direction == 'out' and out.delivered and out.moderator is None
    assert 'Ответ от анонимного админа' in env.session.texts_to(111)[-1]


def test_anonymous_admin_can_ban(env):
    fb = complete_flow(env)
    feed(env, anonymous_admin_msg('/ban', card_message(fb)))
    assert FeedbackUser.objects.get(external_user_id='111').is_banned


def test_anonymous_sender_from_other_chat_is_not_trusted(env):
    """«Анонимность» из чужого чата (sender_chat != админ-чат) не даёт прав."""
    fb = complete_flow(env)
    env.session.calls.clear()
    feed(env, anonymous_admin_msg('подделка', card_message(fb), sender_chat_id=-100999))
    assert not fb.messages.exists() and not env.session.texts_to(111)


def test_reply_button_sends_force_reply_prompt(env):
    fb = complete_flow(env)
    env.session.calls.clear()
    feed(env, press(900, f'fb:{fb.pk}:reply', chat_id=ADMIN_CHAT))
    prompt = [c for c in env.session.sent() if c.chat_id == ADMIN_CHAT][0]
    assert f'№{fb.pk}' in prompt.text and prompt.reply_markup.force_reply is True
    assert prompt.message_thread_id == fb.admin_thread_id
    assert not env.session.texts_to(111)  # пользователю пока ничего не ушло


def test_reply_to_prompt_is_delivered_to_user(env):
    fb = complete_flow(env)
    prompt = Message(
        message_id=8800, date=NOW, chat=Chat(id=ADMIN_CHAT, type='supergroup'),
        from_user=User(id=1, is_bot=True, first_name='bot'),
        text=f'✍️ Ответ по обращению №{fb.pk}. Напишите ответом на это сообщение — текст уйдёт пользователю.',
    )
    env.session.calls.clear()
    feed(env, msg(900, 'Ответ через кнопку', chat_id=ADMIN_CHAT, chat_type='supergroup', reply_to=prompt))
    assert 'Ответ через кнопку' in env.session.texts_to(111)[-1]
    assert fb.messages.get().delivered


def test_reply_button_ignored_for_non_moderator(env):
    fb = complete_flow(env)
    env.session.calls.clear()
    feed(env, press(555, f'fb:{fb.pk}:reply', chat_id=ADMIN_CHAT))
    assert not [c for c in env.session.sent() if c.chat_id == ADMIN_CHAT]
