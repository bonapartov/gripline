"""
Адаптер Telegram (aiogram 3) для ядра обращений.

Весь Telegram-специфичный код — здесь и в website/feedback/telegram_bot.py.
Тексты пользователей экранируются html.escape перед отправкой в админ-чат
(parse mode HTML) — форматированием нельзя ни сломать разметку, ни
подсунуть ссылку.
"""
import asyncio
import html
import io
import logging
from typing import Optional, Sequence

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import (
    TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter,
)
from aiogram.types import ForceReply, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from website.feedback import service
from website.feedback.channels.base import ChannelAdapter, DeliveryError
from website.feedback.db import run_sync
from website.models import FEEDBACK_CHANNEL_TELEGRAM, Feedback, FeedbackBotSettings

logger = logging.getLogger('feedback')

CARD_LIMIT = 3900          # лимит Telegram на сообщение — 4096
ADMIN_MIN_INTERVAL = 0.4   # сек между сообщениями в админ-чат (антифлуд группы)
ADMIN_RETRIES = 5

STATUS_LABELS = {
    Feedback.STATUS_NEW: '🆕 Новое',
    Feedback.STATUS_IN_WORK: '🔧 В работе',
    Feedback.STATUS_DONE: '✅ Закрыто',
}


def normalize_proxy(proxy_url):
    """aiohttp-socks не знает схему socks5h (она значит «DNS на стороне
    прокси» — для socks5 в python-socks это и так поведение по умолчанию)."""
    if proxy_url and proxy_url.startswith('socks5h://'):
        return 'socks5://' + proxy_url[len('socks5h://'):]
    return proxy_url


def build_bot(token, proxy_url=None):
    session = AiohttpSession(proxy=normalize_proxy(proxy_url)) if proxy_url else AiohttpSession()
    return Bot(token=token, session=session, default=DefaultBotProperties(parse_mode=None))


def make_markup(rows):
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=data) for label, data in row] for row in rows
    ])


def _label(step):
    """Подпись поля в карточке — первая фраза вопроса: «Где ошибка? …» → «Где ошибка»."""
    first = step.prompt_text.strip().replace('\n', ' ')
    for sep in ('?', '.', '!'):
        if sep in first:
            first = first.split(sep, 1)[0]
    return first.strip()[:60] or step.key


def _clip(value, limit):
    return value if len(value) <= limit else value[:limit - 1] + '…'


def _card_sync(feedback_id):
    """Собирает (HTML-текст, кнопки) карточки. Синхронно — трогает ORM."""
    fb = Feedback.objects.select_related('category', 'user', 'assigned_to').get(pk=feedback_id)
    e = html.escape
    category = f'{fb.category.emoji} {fb.category.title}'.strip() if fb.category else 'Без категории'
    lines = [f'<b>№{fb.pk}</b> · {e(category)}']

    if fb.anonymized_at:
        lines.append(f'Статус: {STATUS_LABELS[fb.status]}')
        lines.append('')
        lines.append(f'<i>{e(service.DELETED_NOTE)}</i>')
        return '\n'.join(lines), None

    if fb.user and fb.user.channel != FEEDBACK_CHANNEL_TELEGRAM:
        lines.append('От: пользователь приложения GripLine SetupKart')
        lines.append('<i>Ответ — только по e-mail (если указан, он в письме администратору)</i>')
    elif fb.user:
        who = f'@{fb.user.username}' if fb.user.username else (fb.user.display_name or 'без имени')
        lines.append(f'От: {e(who)} (id {e(fb.user.external_user_id)})')
    src = service.source_info(fb)
    if src:
        kinds = {'stage': 'Этап', 'pilot': 'Пилот', 'track': 'Трасса', 'champ': 'Чемпионат',
                 'hub': 'Этап (общая страница)', 'rating': 'Рейтинг'}
        lines.append(f'Источник: {kinds.get(src.kind, "")} «{e(src.title)}» → <a href="{e(src.url, quote=True)}">{e(src.url)}</a>')
    status = STATUS_LABELS[fb.status]
    if fb.status == Feedback.STATUS_IN_WORK and fb.assigned_to:
        status += f': {e(fb.assigned_to.name)}'
    lines.append(f'Статус: {status}')
    lines.append('')

    labels = {s.key: _label(s) for s in fb.category.steps.all()} if fb.category else {}
    for key, value in fb.answers.items():
        lines.append(f'<b>{e(labels.get(key, key))}:</b> {e(_clip(str(value), 1500))}')
    count = fb.attachments.count()
    if count:
        lines.append(f'\nВложения: {count} файл.')
    body = '\n'.join(lines)
    if len(body) > CARD_LIMIT:
        body = body[:CARD_LIMIT - 1] + '…'

    # из приложения ответить в Telegram нельзя — кнопку «Ответить» не показываем
    from_app = fb.user is not None and fb.user.channel != FEEDBACK_CHANNEL_TELEGRAM
    reply = [] if from_app else [('Ответить', f'fb:{fb.pk}:reply')]
    if fb.status == Feedback.STATUS_NEW:
        rows = [[('В работу', f'fb:{fb.pk}:work'), *reply, ('Закрыто', f'fb:{fb.pk}:done')]]
    elif fb.status == Feedback.STATUS_IN_WORK:
        rows = [[*reply, ('Закрыто', f'fb:{fb.pk}:done')]]
    else:
        rows = [[('Вернуть в работу', f'fb:{fb.pk}:work'), *reply]]
    return body, rows


class TelegramAdapter(ChannelAdapter):
    channel = 'telegram'

    def __init__(self, bot: Bot):
        self.bot = bot
        self._admin_lock = asyncio.Lock()

    # --- пользователю ---
    async def send_message(self, user, text, buttons: Optional[Sequence] = None):
        if getattr(user, 'channel', FEEDBACK_CHANNEL_TELEGRAM) != FEEDBACK_CHANNEL_TELEGRAM:
            # обращение из приложения SetupKart: входящих сообщений там нет, ответ — только по e-mail
            raise DeliveryError('обращение из приложения — ответ только по e-mail (адрес в письме администратору)')
        try:
            msg = await self.bot.send_message(int(user.external_user_id), text, reply_markup=make_markup(buttons))
        except TelegramForbiddenError as exc:
            raise DeliveryError('Пользователь заблокировал бота') from exc
        except TelegramBadRequest as exc:
            raise DeliveryError(f'Telegram отклонил сообщение: {exc.message[:100]}') from exc
        return msg.message_id

    # --- в админ-чат (очередь с повтором при 429) ---
    async def _admin_call(self, factory):
        async with self._admin_lock:
            for attempt in range(ADMIN_RETRIES):
                try:
                    result = await factory()
                    await asyncio.sleep(ADMIN_MIN_INTERVAL)
                    return result
                except TelegramRetryAfter as exc:
                    logger.warning('Админ-чат: flood control, ждём %s с', exc.retry_after)
                    await asyncio.sleep(exc.retry_after + 1)
            raise DeliveryError('Админ-чат недоступен: превышены повторы после 429')

    async def send_to_admin(self, feedback):
        cfg = await run_sync(FeedbackBotSettings.get)
        if not cfg.admin_chat_id:
            logger.warning('admin_chat_id не задан — карточка №%s не отправлена', feedback.pk)
            return None, None
        body, rows = await run_sync(_card_sync, feedback.pk)
        thread_id = await run_sync(lambda: feedback.category.admin_topic_id if feedback.category else None)

        async def send(thread):
            return await self.bot.send_message(
                cfg.admin_chat_id, body, parse_mode='HTML', reply_markup=make_markup(rows),
                message_thread_id=thread, disable_web_page_preview=True,
            )

        try:
            msg = await self._admin_call(lambda: send(thread_id))
        except TelegramBadRequest as exc:
            if thread_id and 'thread' in str(exc).lower():
                logger.warning('Тема %s не найдена — отправляем в общий чат', thread_id)
                thread_id = None
                msg = await self._admin_call(lambda: send(None))
            else:
                raise
        await self._send_attachments(feedback, cfg.admin_chat_id, thread_id, msg.message_id)
        return msg.message_id, thread_id

    async def _send_attachments(self, feedback, chat_id, thread_id, reply_to):
        atts = await run_sync(lambda: list(feedback.attachments.all()))
        for att in atts:
            path = await run_sync(lambda a=att: a.file.path)
            name = att.original_name or path.rsplit('/', 1)[-1]

            async def send(a=att, p=path, n=name):
                return await self.bot.send_document(
                    chat_id, FSInputFile(p, filename=n), message_thread_id=thread_id,
                    reply_to_message_id=reply_to,
                )
            try:
                await self._admin_call(send)
            except Exception:
                logger.exception('Не удалось отправить вложение id=%s в админ-чат', att.pk)

    async def send_admin_text(self, feedback, text_html, reply_to=None, force_reply=False, buttons=None):
        """Сообщение в тему обращения (диалог, служебные заметки). Возвращает message_id."""
        cfg = await run_sync(FeedbackBotSettings.get)
        if not cfg.admin_chat_id:
            return None

        async def send():
            return await self.bot.send_message(
                cfg.admin_chat_id, text_html, parse_mode='HTML',
                message_thread_id=feedback.admin_thread_id,
                reply_to_message_id=reply_to or feedback.admin_chat_message_id,
                disable_web_page_preview=True,
                reply_markup=(
                    ForceReply(force_reply=True, input_field_placeholder='Ответ пользователю…')
                    if force_reply else make_markup(buttons)
                ),
            )
        try:
            return (await self._admin_call(send)).message_id
        except TelegramBadRequest:
            # исходная карточка/тема удалена — пишем без привязки
            async def send_plain():
                return await self.bot.send_message(cfg.admin_chat_id, text_html, parse_mode='HTML')
            return (await self._admin_call(send_plain)).message_id

    async def update_admin_card(self, feedback):
        if not feedback.admin_chat_message_id:
            return
        cfg = await run_sync(FeedbackBotSettings.get)
        if not cfg.admin_chat_id:
            return
        body, rows = await run_sync(_card_sync, feedback.pk)
        try:
            await self._admin_call(lambda: self.bot.edit_message_text(
                body, chat_id=cfg.admin_chat_id, message_id=feedback.admin_chat_message_id,
                parse_mode='HTML', reply_markup=make_markup(rows), disable_web_page_preview=True,
            ))
        except TelegramBadRequest as exc:
            if 'not modified' not in str(exc).lower():
                logger.warning('Карточка №%s не обновлена: %s', feedback.pk, exc.message[:120])

    # --- вложения ---
    async def download_attachment(self, ref):
        file = await self.bot.get_file(ref)
        buf = io.BytesIO()
        await self.bot.download_file(file.file_path, buf)
        return buf.getvalue()
