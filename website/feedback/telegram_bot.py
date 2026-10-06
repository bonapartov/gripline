"""
Процесс Telegram-бота обратной связи: обработчики + supervisor.

Запуск: manage.py run_feedback_bot (systemd, Restart=always). Long polling.
Настройки (тексты, лимиты, сценарии) читаются из БД при каждой операции,
поэтому применяются без перезапуска; supervisor раз в settings_refresh_sec
следит только за тем, что требует пересоздания клиента — токеном, прокси,
флагом «включён» и кнопкой «Перезапустить бота» — и тогда корректно
завершает процесс (systemd поднимает его с новыми параметрами).
"""
import asyncio
import html
import logging
import re
import secrets
import signal
import time
from dataclasses import dataclass
from typing import Optional

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, ReactionTypeEmoji
from asgiref.sync import sync_to_async
from django.db import close_old_connections
from django.utils import timezone

from website.feedback import service, sources
from website.feedback.channels.base import DeliveryError
from website.feedback.channels.telegram import TelegramAdapter, build_bot
from website.models import Feedback, FeedbackBotSettings, FeedbackStep

logger = logging.getLogger('feedback')

CHANNEL = 'telegram'
# Сообщения анонимного администратора группы приходят от этого «пользователя»
ANONYMOUS_ADMIN_ID = 1087968824
# Сколько секунд после «Ответить» следующее сообщение в теме уходит пользователю
PENDING_REPLY_TTL = 300
HEARTBEAT_SEC = 30


def run_sync(func, *args, **kwargs):
    return sync_to_async(func, thread_sensitive=True)(*args, **kwargs)


@dataclass(frozen=True)
class Snapshot:
    """То, смена чего требует пересоздания клиента Telegram."""
    enabled: bool
    token: str
    proxy: Optional[str]
    restart_at: Optional[str]
    refresh_sec: int


def load_snapshot():
    cfg = FeedbackBotSettings.get()
    return Snapshot(
        enabled=cfg.is_enabled, token=cfg.get_token(), proxy=cfg.proxy_url(),
        restart_at=cfg.restart_requested_at.isoformat() if cfg.restart_requested_at else None,
        refresh_sec=max(cfg.settings_refresh_sec, 10),
    )


class TokenRedactFilter(logging.Filter):
    """Токен бота никогда не попадает в логи (он есть в URL Bot API)."""
    def __init__(self, token):
        super().__init__()
        self.token = token

    def filter(self, record):
        if self.token:
            try:
                msg = record.getMessage()
            except Exception:
                return True
            if self.token in msg:
                record.msg, record.args = msg.replace(self.token, '***'), ()
        return True


class FeedbackTelegramBot:
    def __init__(self, token, proxy):
        self.bot = build_bot(token, proxy)
        self.adapter = TelegramAdapter(self.bot)
        self.dp = Dispatcher()
        # (chat_id, thread_id) -> (feedback_id, истекает). Только в памяти: TTL 5 минут,
        # потеря при перезапуске бота безвредна.
        self._pending_replies = {}
        # token -> (feedback_id, текст, id исходного сообщения, истекает): ответы без reply
        # ждут подтверждения «Да/Отмена» перед отправкой пользователю
        self._confirmations = {}
        self.router = Router()
        self.dp.include_router(self.router)
        self._register()

    # ---------- общие помощники ----------

    async def _user(self, tg_user):
        return await run_sync(
            service.get_or_create_user, CHANNEL, tg_user.id,
            tg_user.username or '', tg_user.full_name or '',
        )

    async def _menu_rows(self):
        cats = await run_sync(service.active_categories)
        return [[(f'{c.emoji} {c.title}'.strip(), f'cat:{c.pk}')] for c in cats]

    async def _show_menu(self, user):
        rows = await self._menu_rows()
        if not rows:
            await self.adapter.send_message(user, await run_sync(service.text, 'no_categories'))
            return
        await self.adapter.send_message(user, await run_sync(service.text, 'welcome'), rows)

    async def _present(self, user, outcome):
        """Показать пользователю результат шага сценария."""
        T = lambda key, **v: run_sync(service.text, key, **v)
        kind, step = outcome.kind, outcome.step
        if kind == 'ask':
            await self._ask(user, step)
        elif kind == 'saved':
            rows = [[(await T('btn_done'), 'done')]]
            await self.adapter.send_message(user, await T('attachment_saved', **outcome.variables), rows)
        elif kind == 'too_long':
            await self.adapter.send_message(user, await T('text_too_long', **outcome.variables))
        elif kind == 'rejected':
            await self.adapter.send_message(user, await T('file_rejected', **outcome.variables))
        elif kind == 'expect_text':
            await self.adapter.send_message(user, await T('expect_text'))
        elif kind == 'expect_file':
            await self.adapter.send_message(user, await T('expect_file'))
        elif kind == 'rate_limited':
            await self.adapter.send_message(user, await T('rate_limited'))
        elif kind == 'autoreply':
            await self.adapter.send_message(user, outcome.text)
        elif kind == 'complete':
            rows = [[(await T('btn_send_more'), 'menu')]]
            await self.adapter.send_message(user, await T('success', number=outcome.feedback.pk), rows)
            await self._notify_admin(outcome.feedback)

    async def _ask(self, user, step):
        T = lambda key: run_sync(service.text, key)
        rows = []
        if step.type == FeedbackStep.TYPE_ATTACHMENT:
            rows.append([(await T('btn_done'), 'done')])
        if step.skip_button_text:
            rows.append([(step.skip_button_text, 'skip')])
        rows.append([(await T('btn_cancel'), 'cancel')])
        await self.adapter.send_message(user, step.prompt_text, rows)

    async def _notify_admin(self, feedback):
        try:
            message_id, thread_id = await self.adapter.send_to_admin(feedback)
            if message_id:
                await run_sync(service.set_admin_card, feedback, message_id, thread_id)
        except Exception:
            # обращение уже в БД и видно в админке; пользователю ошибку не показываем
            logger.exception('Карточка обращения №%s не доставлена в админ-чат', feedback.pk)

    async def _is_admin_chat(self, chat_id):
        cfg = await run_sync(FeedbackBotSettings.get)
        return bool(cfg.admin_chat_id) and chat_id == cfg.admin_chat_id

    # ---------- регистрация обработчиков ----------

    def _register(self):
        r = self.router
        private = F.chat.type == 'private'

        @self.dp.update.outer_middleware()
        async def db_connections(handler, event, data):
            # долгоживущий процесс: не держим мёртвые соединения с PostgreSQL
            await run_sync(close_old_connections)
            return await handler(event, data)

        @r.message(private, CommandStart())
        async def on_start(message: Message, command: CommandObject):
            user = await self._user(message.from_user)
            if user.is_banned:
                return
            if user.privacy_notice_shown_at is None:
                cfg = await run_sync(FeedbackBotSettings.get)
                await self.adapter.send_message(
                    user, await run_sync(service.text, 'privacy_notice', policy_url=cfg.privacy_policy_url),
                )
                await run_sync(service.mark_privacy_notice_shown, user)
            parsed = sources.parse_start_param(command.args)
            if parsed:
                code, kind, pk = parsed
                category = await run_sync(service.category_by_code, code)
                # объект ссылки должен существовать; без объекта (kind=None) — просто категория
                resolved = await run_sync(sources.resolve, kind, pk) if kind else None
                if category and (resolved or kind is None):
                    outcome = await run_sync(
                        service.begin, user, category, kind if resolved else '', pk if resolved else None,
                    )
                    await self._present(user, outcome)
                    return
            await self._show_menu(user)

        @r.message(private, Command('cancel'))
        async def on_cancel(message: Message):
            user = await self._user(message.from_user)
            if user.is_banned:
                return
            await run_sync(service.cancel, user)
            await self.adapter.send_message(user, await run_sync(service.text, 'cancelled'))

        @r.message(private, Command('id'))
        async def on_id(message: Message):
            # нужен, чтобы добавить модератора в админке (там просят числовой ID)
            await message.answer(f'Ваш Telegram ID: {message.from_user.id}')

        @r.message(private, Command('forget'))
        async def on_forget(message: Message):
            user = await self._user(message.from_user)
            if user.is_banned:
                return
            T = lambda key: run_sync(service.text, key)
            rows = [[(await T('btn_forget_yes'), 'forget:yes'), (await T('btn_forget_no'), 'forget:no')]]
            await self.adapter.send_message(user, await T('forget_confirm'), rows)

        @r.callback_query(F.data == 'forget:yes')
        async def on_forget_yes(cb: CallbackQuery):
            await cb.answer()
            user = await self._user(cb.from_user)
            if user.is_banned:
                return
            # после forget_user запись пользователя может быть удалена — пишем напрямую
            affected = await run_sync(service.forget_user, user)
            await cb.message.answer(await run_sync(service.text, 'forget_done'))
            for fb in affected:
                try:
                    await self.adapter.update_admin_card(fb)
                except Exception:
                    logger.exception('Карточка №%s не перерисована после /forget', fb.pk)

        @r.callback_query(F.data == 'forget:no')
        async def on_forget_no(cb: CallbackQuery):
            await cb.answer()
            await cb.message.delete()

        @r.callback_query(F.data.startswith('cat:'))
        async def on_category(cb: CallbackQuery):
            await cb.answer()
            user = await self._user(cb.from_user)
            if user.is_banned:
                return
            try:
                category_id = int(cb.data.split(':', 1)[1])
            except ValueError:
                return
            cats = await run_sync(service.active_categories)
            category = next((c for c in cats if c.pk == category_id), None)
            if category is None:
                await self._show_menu(user)
                return
            outcome = await run_sync(service.begin, user, category)
            await self._present(user, outcome)

        @r.callback_query(F.data == 'menu')
        async def on_menu(cb: CallbackQuery):
            await cb.answer()
            user = await self._user(cb.from_user)
            if not user.is_banned:
                await self._show_menu(user)

        @r.callback_query(F.data == 'cancel')
        async def on_cancel_button(cb: CallbackQuery):
            await cb.answer()
            user = await self._user(cb.from_user)
            if user.is_banned:
                return
            await run_sync(service.cancel, user)
            await self.adapter.send_message(user, await run_sync(service.text, 'cancelled'))

        @r.callback_query(F.data.in_({'skip', 'done'}))
        async def on_flow_button(cb: CallbackQuery):
            await cb.answer()
            user = await self._user(cb.from_user)
            if user.is_banned:
                return
            draft = await run_sync(service.get_draft, user)
            if draft is None:
                await self._show_menu(user)
                return
            func = service.skip_step if cb.data == 'skip' else service.done_attachments
            await self._present(user, await run_sync(func, draft))

        @r.message(private, F.text & ~F.text.startswith('/'))
        async def on_text(message: Message):
            user = await self._user(message.from_user)
            if user.is_banned:
                return
            draft = await run_sync(service.get_draft, user)
            if draft is not None:
                await self._present(user, await run_sync(service.answer_text, draft, message.text))
                return
            await self._dialog_message(user, message)

        @r.message(private, F.photo | F.document)
        async def on_file(message: Message):
            user = await self._user(message.from_user)
            if user.is_banned:
                return
            draft = await run_sync(service.get_draft, user)
            if draft is None:
                await self.adapter.send_message(user, await run_sync(service.text, 'dialog_text_only'))
                return
            if message.photo:
                media, name = message.photo[-1], 'photo.jpg'
            else:
                media, name = message.document, message.document.file_name or ''
            cfg = await run_sync(FeedbackBotSettings.get)
            if media.file_size and media.file_size > cfg.max_file_size_mb * 1024 * 1024:
                outcome = service.Outcome('rejected', variables={
                    'max_mb': cfg.max_file_size_mb, 'types': ', '.join(cfg.allowed_types_list()),
                })
                await self._present(user, outcome)
                return
            try:
                data = await self.adapter.download_attachment(media.file_id)
            except Exception:
                logger.exception('Не удалось скачать вложение')
                await self.adapter.send_message(user, await run_sync(service.text, 'error_generic'))
                return
            await self._present(user, await run_sync(service.add_attachment, draft, data, name))

        # --- админ-чат ---
        @r.callback_query(F.data.regexp(r'^fb:\d+:(work|done|reply)$'))
        async def on_status_button(cb: CallbackQuery):
            if not cb.message or not await self._is_admin_chat(cb.message.chat.id):
                await cb.answer()
                return
            moderator = await run_sync(service.get_moderator, CHANNEL, cb.from_user.id)
            if moderator is None:
                await cb.answer()  # немодератор: ничего не происходит
                return
            _, fb_id, action = cb.data.split(':')
            fb = await run_sync(lambda: Feedback.objects.select_related('user').filter(pk=int(fb_id)).first())
            if fb is None or fb.anonymized_at:
                await cb.answer('Обращение недоступно')
                return
            if action == 'reply':
                await cb.answer()
                if fb.user is None:
                    await cb.message.answer('Данные пользователя удалены — ответить нельзя.')
                    return
                # ForceReply сам открывает у модератора поле «ответа на сообщение»;
                # обращение находится по «№N» в тексте подсказки (_feedback_from_reply)
                self._pending_replies[self._thread_key(cb.message)] = (fb.pk, time.monotonic() + PENDING_REPLY_TTL)
                await self.adapter.send_admin_text(
                    fb, f'✍️ Ответ по обращению <b>№{fb.pk}</b>. Следующее сообщение в этой теме '
                        f'(в течение {PENDING_REPLY_TTL // 60} мин) уйдёт пользователю.',
                    reply_to=fb.admin_chat_message_id, force_reply=True,
                )
                return
            status = Feedback.STATUS_IN_WORK if action == 'work' else Feedback.STATUS_DONE
            changed = await run_sync(service.change_status, fb, status, moderator)
            await cb.answer()
            await self.adapter.update_admin_card(fb)
            if changed and fb.user:
                key = 'status_in_work' if status == Feedback.STATUS_IN_WORK else 'status_done'
                try:
                    await self.adapter.send_message(fb.user, await run_sync(service.text, key, number=fb.pk))
                except DeliveryError:
                    logger.info('Уведомление о статусе №%s не доставлено', fb.pk)

        @r.message(F.chat.type.in_({'group', 'supergroup'}), Command('ban', 'unban'))
        async def on_ban(message: Message, command: CommandObject):
            if not await self._is_admin_chat(message.chat.id):
                return
            allowed, _ = await self._moderator_of(message)
            if not allowed:
                return
            fb = await self._feedback_from_reply(message)
            if fb is None or fb.user is None:
                await message.reply('Сделайте /ban ответом на карточку обращения (данные пользователя должны быть не удалены).')
                return
            banned = command.command == 'ban'
            await run_sync(service.set_banned, fb.user, banned, (command.args or '')[:255])
            await message.reply('Пользователь заблокирован.' if banned else 'Пользователь разблокирован.')

        @r.message(F.chat.type.in_({'group', 'supergroup'}), F.text & ~F.text.startswith('/'))
        async def on_moderator_reply(message: Message):
            if not await self._is_admin_chat(message.chat.id):
                return
            allowed, moderator = await self._moderator_of(message)
            if not allowed:
                return
            fb = await self._feedback_from_reply(message)
            if fb is not None:
                # явный reply на карточку/сообщение обращения — однозначно, шлём сразу
                if fb.user is None:
                    await message.reply('Данные пользователя удалены — ответить нельзя.')
                    return
                await self._deliver_reply(fb, message.text, moderator, message.chat.id, message.message_id)
                return
            fb = await self._pending_feedback(message)
            if fb is None:
                return
            if fb.user is None:
                await message.reply('Данные пользователя удалены — ответить нельзя.')
                return
            # без reply адресат определён только кнопкой «Ответить» (одна на тему) —
            # переспрашиваем, чтобы текст не ушёл не тому пользователю
            token = secrets.token_hex(4)
            self._confirmations[token] = (fb.pk, message.text, message.message_id, time.monotonic() + PENDING_REPLY_TTL)
            preview = html.escape(message.text if len(message.text) <= 500 else message.text[:500] + '…')
            await self.adapter.send_admin_text(
                fb, f'Отправить пользователю по <b>№{fb.pk}</b>?\n\n<i>{preview}</i>',
                reply_to=message.message_id,
                buttons=[[('✅ Отправить', f'fbc:{token}:yes'), ('Отмена', f'fbc:{token}:no')]],
            )

        @r.callback_query(F.data.regexp(r'^fbc:[0-9a-f]{8}:(yes|no)$'))
        async def on_confirm_reply(cb: CallbackQuery):
            if not cb.message or not await self._is_admin_chat(cb.message.chat.id):
                await cb.answer()
                return
            moderator = await run_sync(service.get_moderator, CHANNEL, cb.from_user.id)
            if moderator is None:
                await cb.answer()  # не модератор: ничего не происходит, подтверждение остаётся
                return
            _, token, answer = cb.data.split(':')
            entry = self._confirmations.pop(token, None)
            if entry is None or time.monotonic() > entry[3]:
                await cb.answer('Устарело — нажмите «Ответить» ещё раз')
                await cb.message.edit_text('Подтверждение устарело.')
                return
            fb_id, text, original_id, _ = entry
            await cb.answer()
            if answer == 'no':
                await cb.message.edit_text('Отменено, пользователю ничего не отправлено.')
                return
            fb = await run_sync(
                lambda: _with_user(Feedback.objects.select_related('user').filter(pk=fb_id).first()),
            )
            if fb is None or fb.user is None:
                await cb.message.edit_text('Данные пользователя удалены — ответить нельзя.')
                return
            delivered = await self._deliver_reply(fb, text, moderator, cb.message.chat.id, original_id)
            await cb.message.edit_text(
                f'✅ Отправлено по №{fb.pk}.' if delivered else f'⚠️ По №{fb.pk} не доставлено.',
            )

    async def _deliver_reply(self, fb, text, moderator, chat_id, original_message_id):
        """Отправить ответ модератора пользователю и записать в историю диалога."""
        prefix = await run_sync(service.text, 'reply_prefix', number=fb.pk)
        delivered = True
        try:
            await self.adapter.send_message(fb.user, f'{prefix}\n\n{text}')
        except DeliveryError as exc:
            delivered = False
            await self.adapter.send_admin_text(
                fb, f'⚠️ Не доставлено: {html.escape(str(exc))}', reply_to=original_message_id,
            )
        await run_sync(service.add_message, fb, 'out', text, moderator, original_message_id, delivered)
        if delivered:
            try:
                await self.bot.set_message_reaction(
                    chat_id, original_message_id, reaction=[ReactionTypeEmoji(emoji='👍')],
                )
            except Exception:
                pass  # реакции — удобство, не критичный путь
        return delivered

    @staticmethod
    def _thread_key(message: Message):
        thread = message.message_thread_id if message.is_topic_message else None
        return message.chat.id, thread

    async def _pending_feedback(self, message: Message):
        """Обращение, на которое модератор нажал «Ответить» (одноразово, с TTL)."""
        key = self._thread_key(message)
        entry = self._pending_replies.get(key)
        if entry is None:
            return None
        feedback_id, expires = entry
        del self._pending_replies[key]
        if time.monotonic() > expires:
            return None
        return await run_sync(
            lambda: _with_user(Feedback.objects.select_related('user').filter(pk=feedback_id).first()),
        )

    async def _moderator_of(self, message: Message):
        """(допущен ли автор, модератор|None). Анонимный администратор группы
        (сообщение «от имени группы») допускается без привязки к человеку:
        писать в закрытую админ-группу могут только её администраторы."""
        sender = message.from_user
        if (
            sender is not None and sender.id == ANONYMOUS_ADMIN_ID
            and message.sender_chat is not None and message.sender_chat.id == message.chat.id
        ):
            return True, None
        if sender is None:
            return False, None
        moderator = await run_sync(service.get_moderator, CHANNEL, sender.id)
        return moderator is not None, moderator

    async def _feedback_from_reply(self, message: Message):
        target = message.reply_to_message
        if target is None:
            return None
        fb = await run_sync(
            lambda: _with_user(service.find_feedback_by_admin_message(target.message_id)),
        )
        if fb is not None:
            return fb
        # подсказка кнопки «Ответить» и прочие сообщения бота с «№N» в тексте
        if target.from_user is not None and target.from_user.is_bot and target.text:
            m = re.search(r'№(\d+)', target.text)
            if m:
                return await run_sync(
                    lambda: _with_user(Feedback.objects.select_related('user').filter(pk=int(m.group(1))).first()),
                )
        return None

    async def _dialog_message(self, user, message: Message):
        """Сообщение вне сценария: к открытому обращению — в его тему,
        иначе подсказка открыть новое через меню."""
        fb = await run_sync(service.latest_open_feedback, user)
        if fb is None:
            has_any = await run_sync(user.feedbacks.exists)
            key = 'dialog_closed' if has_any else 'no_active_draft'
            await self._show_menu_with_note(user, key)
            return
        body = f'💬 <b>№{fb.pk}</b> · {html.escape(str(user))}:\n{html.escape(message.text)}'
        admin_msg_id = await self.adapter.send_admin_text(fb, body)
        await run_sync(service.add_message, fb, 'in', message.text, None, admin_msg_id, True)
        await self.adapter.send_message(user, await run_sync(service.text, 'dialog_added', number=fb.pk))

    async def _show_menu_with_note(self, user, key):
        rows = await self._menu_rows()
        await self.adapter.send_message(user, await run_sync(service.text, key), rows or None)


def _with_user(fb):
    if fb is not None:
        fb.user  # подгрузить в синхронном контексте
    return fb


# ---------- supervisor ----------

async def _heartbeat_loop():
    while True:
        try:
            await run_sync(
                lambda: FeedbackBotSettings.objects.filter(pk=1).update(heartbeat_at=timezone.now()),
            )
        except Exception:
            logger.exception('heartbeat не записан')
        await asyncio.sleep(HEARTBEAT_SEC)


async def _run_session(snapshot, stop_event):
    """Одна сессия polling'а с фиксированными токеном/прокси. Возвращается,
    когда supervisor увидел изменение настроек (→ процесс завершается)."""
    app = FeedbackTelegramBot(snapshot.token, snapshot.proxy)
    redact = TokenRedactFilter(snapshot.token)
    for name in ('feedback', 'aiogram', 'aiohttp'):
        logging.getLogger(name).addFilter(redact)

    polling = asyncio.create_task(app.dp.start_polling(
        app.bot, handle_signals=False, close_bot_session=False,
        allowed_updates=['message', 'callback_query'],
    ))

    async def watch():
        while True:
            await asyncio.sleep(snapshot.refresh_sec)
            try:
                current = await run_sync(load_snapshot)
            except Exception:
                logger.exception('Не удалось перечитать настройки')
                continue
            if current != snapshot:
                logger.info('Настройки бота изменились — перезапуск процесса')
                return

    watcher = asyncio.create_task(watch())
    stopper = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait({polling, watcher, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if polling in done and polling.exception():
            raise polling.exception()
    finally:
        try:
            await app.dp.stop_polling()
        except Exception:
            pass
        polling.cancel()
        watcher.cancel()
        stopper.cancel()
        await app.bot.session.close()


async def run_forever():
    await run_sync(service.ensure_texts)
    # SIGTERM от systemd: дообработать текущие апдейты и выйти
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
    heartbeat = asyncio.create_task(_heartbeat_loop())
    try:
        while True:
            snapshot = await run_sync(load_snapshot)
            if stop_event.is_set():
                return
            if not snapshot.enabled or not snapshot.token:
                logger.info('Бот выключен или токен не задан — ожидание настроек')
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=snapshot.refresh_sec)
                except asyncio.TimeoutError:
                    pass
                continue
            logger.info('Запуск polling (прокси: %s)', 'да' if snapshot.proxy else 'нет')
            try:
                await _run_session(snapshot, stop_event)
            except Exception:
                logger.exception('Сессия бота завершилась с ошибкой; повтор через 15 с')
                await asyncio.sleep(15)
                continue
            return  # настройки изменились — выходим, systemd перезапустит
    finally:
        heartbeat.cancel()
