"""
Ядро обработки обращений. Не знает про Telegram/aiogram: работает с
моделями и обычными значениями, каналы подключаются через
channels.base.ChannelAdapter. Все функции синхронные — асинхронные
адаптеры вызывают их через sync_to_async.

Состояние сценария — FeedbackDraft в БД (переживает перезапуск бота).
"""
import logging
import string
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

import filetype
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from website.models import (
    Feedback, FeedbackAttachment, FeedbackBotSettings, FeedbackCategory,
    FeedbackDraft, FeedbackMessage, FeedbackModerator, FeedbackStep,
    FeedbackText, FeedbackUser,
)
from . import autoreply, sources
from .texts import DEFAULT_TEXTS

logger = logging.getLogger('feedback')

DRAFT_TTL = timedelta(hours=24)
OPEN_STATUSES = (Feedback.STATUS_NEW, Feedback.STATUS_IN_WORK)
DELETED_NOTE = 'Данные удалены по запросу пользователя'


# ---------- тексты ----------

class _SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def render(template, **variables):
    """format с безопасной подстановкой: неизвестные {переменные} и
    произвольные фигурные скобки в тексте админа не роняют бота."""
    try:
        return string.Formatter().vformat(template, (), _SafeDict(variables))
    except (ValueError, IndexError, KeyError, AttributeError):
        return template


def text(key, **variables):
    obj = FeedbackText.objects.filter(key=key).first()
    template = obj.text if obj and obj.text.strip() else DEFAULT_TEXTS.get(key, ('', ''))[0]
    return render(template, **variables)


def ensure_texts():
    """Досоздать записи для ключей, добавленных в код после миграции."""
    existing = set(FeedbackText.objects.values_list('key', flat=True))
    for key, (default, description) in DEFAULT_TEXTS.items():
        if key not in existing:
            FeedbackText.objects.create(key=key, text=default, description=description)


# ---------- пользователи / модераторы ----------

def get_or_create_user(channel, external_user_id, username='', display_name=''):
    user, created = FeedbackUser.objects.get_or_create(
        channel=channel, external_user_id=str(external_user_id),
        defaults={'username': username or '', 'display_name': display_name or ''},
    )
    if not created and (user.username != (username or '') or user.display_name != (display_name or '')):
        if user.anonymized_at is None:
            user.username = username or ''
            user.display_name = display_name or ''
            user.save(update_fields=['username', 'display_name'])
    return user


def mark_privacy_notice_shown(user):
    user.privacy_notice_shown_at = timezone.now()
    user.save(update_fields=['privacy_notice_shown_at'])


def get_moderator(channel, external_user_id):
    """Активный модератор или None. Все остальные в админ-чате игнорируются."""
    return FeedbackModerator.objects.filter(
        channel=channel, external_user_id=str(external_user_id), is_active=True,
    ).first()


def set_banned(user, banned=True, reason=''):
    user.is_banned = banned
    user.ban_reason = reason if banned else ''
    user.save(update_fields=['is_banned', 'ban_reason'])


# ---------- категории и шаги ----------

def active_categories():
    return list(FeedbackCategory.objects.filter(is_active=True))


def category_by_code(code):
    return FeedbackCategory.objects.filter(is_active=True, deep_link_code__iexact=code).first()


def effective_steps(draft):
    """Шаги категории с учётом skip_if_source_set."""
    steps = list(draft.category.steps.all())
    if draft.source_kind:
        steps = [s for s in steps if not s.skip_if_source_set]
    return steps


def current_step(draft):
    steps = effective_steps(draft)
    return steps[draft.step_index] if draft.step_index < len(steps) else None


# ---------- результат операции сценария ----------

@dataclass
class Outcome:
    kind: str  # ask | complete | too_long | rejected | saved | rate_limited | autoreply | expect_text | expect_file | no_draft
    step: Optional[FeedbackStep] = None
    feedback: Optional[Feedback] = None
    text: str = ''
    variables: dict = field(default_factory=dict)


# ---------- сценарий ----------

def discard_draft(user):
    """Удалить черновик вместе с загруженными файлами."""
    draft = FeedbackDraft.objects.filter(user=user).first()
    if not draft:
        return
    _delete_attachments(draft.attachments.all())
    draft.delete()


def begin(user, category, source_kind='', source_id=None):
    discard_draft(user)
    draft = FeedbackDraft.objects.create(
        user=user, category=category, source_kind=source_kind or '', source_id=source_id,
    )
    return _advance_or_finish(draft)


def get_draft(user):
    return FeedbackDraft.objects.select_related('category').filter(user=user).first()


def _advance_or_finish(draft):
    step = current_step(draft)
    if step is None:
        return finish(draft)
    return Outcome('ask', step=step)


def _next(draft):
    draft.step_index += 1
    draft.save(update_fields=['step_index', 'answers', 'updated_at'])
    return _advance_or_finish(draft)


def answer_text(draft, value):
    cfg = FeedbackBotSettings.get()
    step = current_step(draft)
    if step is None:
        return finish(draft)
    if step.type != FeedbackStep.TYPE_TEXT:
        return Outcome('expect_file', step=step)
    value = (value or '').strip()
    if not value:
        return Outcome('expect_text', step=step)
    if len(value) > cfg.max_text_length:
        return Outcome('too_long', step=step, variables={'max_len': cfg.max_text_length})
    draft.answers = {**draft.answers, step.key: value}
    return _next(draft)


def can_skip(step):
    return bool(step and step.skip_button_text)


def skip_step(draft):
    step = current_step(draft)
    if step is None or not can_skip(step):
        return Outcome('ask', step=step)
    return _next(draft)


def _normalize_ext(ext):
    ext = (ext or '').lower().lstrip('.')
    return 'jpg' if ext == 'jpeg' else ext


def add_attachment(draft, data, original_name=''):
    """Проверка по содержимому (magic bytes), размеру и количеству; файл
    сохраняется в закрытое хранилище. Возвращает Outcome(saved|rejected|expect_text)."""
    cfg = FeedbackBotSettings.get()
    step = current_step(draft)
    if step is None:
        return finish(draft)
    if step.type != FeedbackStep.TYPE_ATTACHMENT:
        return Outcome('expect_text', step=step)

    reject_vars = {
        'max_mb': cfg.max_file_size_mb,
        'types': ', '.join(cfg.allowed_types_list()),
    }
    if len(data) > cfg.max_file_size_mb * 1024 * 1024:
        return Outcome('rejected', step=step, variables=reject_vars)
    kind = filetype.guess(data)
    allowed = {_normalize_ext(t) for t in cfg.allowed_types_list()}
    if kind is None or _normalize_ext(kind.extension) not in allowed:
        return Outcome('rejected', step=step, variables=reject_vars)

    count = draft.attachments.count()
    if count >= cfg.max_files_per_feedback:
        return _after_attachments(draft, count)

    att = FeedbackAttachment(
        draft=draft, original_name=(original_name or '')[:255],
        mime=kind.mime, size=len(data),
    )
    att.file.save(f'upload.{_normalize_ext(kind.extension)}', ContentFile(data), save=False)
    att.save()
    count += 1
    if count >= cfg.max_files_per_feedback:
        return _after_attachments(draft, count)
    return Outcome('saved', step=step, variables={'count': count, 'max_files': cfg.max_files_per_feedback})


def _after_attachments(draft, count):
    return _next(draft)


def done_attachments(draft):
    """Кнопка «Готово» на шаге с вложениями."""
    step = current_step(draft)
    if step is None:
        return finish(draft)
    if step.type != FeedbackStep.TYPE_ATTACHMENT:
        return Outcome('ask', step=step)
    if step.is_required and not draft.attachments.exists():
        return Outcome('expect_file', step=step)
    return _next(draft)


def recent_count(user, hours=1):
    return Feedback.objects.filter(user=user, created_at__gte=timezone.now() - timedelta(hours=hours)).count()


def is_rate_limited(user):
    cfg = FeedbackBotSettings.get()
    return recent_count(user) >= cfg.rate_limit_per_hour


@transaction.atomic
def _create_feedback(draft):
    fb = Feedback.objects.create(
        user=draft.user, category=draft.category, answers=draft.answers,
        source_kind=draft.source_kind, source_id=draft.source_id,
    )
    draft.attachments.update(feedback=fb, draft=None)
    draft.delete()
    return fb


def finish(draft):
    user = draft.user
    if is_rate_limited(user):
        discard_draft(user)
        return Outcome('rate_limited')
    reply = autoreply.get_provider().match(draft)
    if reply is not None:
        if not reply.still_create_feedback:
            discard_draft(user)
            return Outcome('autoreply', text=reply.text)
    fb = _create_feedback(draft)
    return Outcome('complete', feedback=fb, variables={'number': fb.pk})


def cancel(user):
    had = FeedbackDraft.objects.filter(user=user).exists()
    discard_draft(user)
    return had


# ---------- обращения ----------

def source_info(feedback):
    if not feedback.source_kind or not feedback.source_id:
        return None
    return sources.resolve(feedback.source_kind, feedback.source_id)


def latest_open_feedback(user):
    return Feedback.objects.filter(user=user, status__in=OPEN_STATUSES, anonymized_at__isnull=True).order_by('-created_at').first()


def find_feedback_by_admin_message(message_id):
    """Обращение по id сообщения в админ-чате (карточка или сообщение диалога)."""
    fb = Feedback.objects.filter(admin_chat_message_id=message_id).first()
    if fb:
        return fb
    msg = FeedbackMessage.objects.select_related('feedback').filter(admin_chat_message_id=message_id).first()
    return msg.feedback if msg else None


def set_admin_card(feedback, message_id, thread_id):
    feedback.admin_chat_message_id = message_id
    feedback.admin_thread_id = thread_id
    feedback.save(update_fields=['admin_chat_message_id', 'admin_thread_id'])


def change_status(feedback, status, moderator=None):
    """Возвращает True, если статус действительно изменился (повторное
    нажатие кнопки не должно слать пользователю дубль уведомления)."""
    if feedback.status == status:
        return False
    feedback.status = status
    if status == Feedback.STATUS_IN_WORK:
        feedback.assigned_to = moderator
        feedback.closed_at = None
    elif status == Feedback.STATUS_DONE:
        feedback.closed_at = timezone.now()
        if moderator and not feedback.assigned_to:
            feedback.assigned_to = moderator
    feedback.save()
    return True


def add_message(feedback, direction, body, moderator=None, admin_chat_message_id=None, delivered=False):
    return FeedbackMessage.objects.create(
        feedback=feedback, direction=direction, moderator=moderator, text=body,
        admin_chat_message_id=admin_chat_message_id, delivered=delivered,
    )


# ---------- персональные данные ----------

def _delete_attachments(queryset):
    for att in queryset:
        try:
            if att.file:
                att.file.delete(save=False)
        except Exception:  # файл мог быть удалён вручную — не рвём очистку
            logger.warning('Не удалось удалить файл вложения id=%s', att.pk)
        att.delete()


def anonymize_feedback(feedback):
    """Убрать из обращения всё персональное; статус, категория и даты остаются."""
    _delete_attachments(feedback.attachments.all())
    feedback.messages.all().delete()
    feedback.user = None
    feedback.answers = {}
    feedback.admin_note = ''
    feedback.anonymized_at = timezone.now()
    feedback.save()


def forget_user(user):
    """/forget: анонимизировать все обращения и удалить пользователя
    (заблокированного оставляем без ПД — иначе бан слетит). Возвращает
    обращения, карточки которых нужно перерисовать в админ-чате."""
    discard_draft(user)
    affected = list(user.feedbacks.all())
    for fb in affected:
        anonymize_feedback(fb)
    if user.is_banned:
        user.username = ''
        user.display_name = ''
        user.anonymized_at = timezone.now()
        user.save()
    else:
        user.delete()
    return affected


def cleanup_expired():
    """Анонимизация по сроку хранения + чистка черновиков старше 24 часов.
    Возвращает (список анонимизированных обращений, число удалённых черновиков/пользователей)."""
    cfg = FeedbackBotSettings.get()
    now = timezone.now()
    border = now - timedelta(days=30 * cfg.retention_months)

    affected = list(Feedback.objects.filter(created_at__lt=border, anonymized_at__isnull=True))
    for fb in affected:
        anonymize_feedback(fb)

    stale = FeedbackDraft.objects.filter(updated_at__lt=now - DRAFT_TTL)
    drafts = 0
    for draft in stale:
        _delete_attachments(draft.attachments.all())
        draft.delete()
        drafts += 1

    # Пользователи без обращений, не забаненные, давно не активные — это
    # тоже ПД (username, имя), хранить дольше срока незачем.
    users = FeedbackUser.objects.filter(
        first_seen_at__lt=border, is_banned=False, feedbacks__isnull=True, draft__isnull=True,
    )
    removed_users = users.count()
    users.delete()
    # у забаненных после срока оставляем только факт бана
    FeedbackUser.objects.filter(first_seen_at__lt=border, is_banned=True, anonymized_at__isnull=True).update(
        username='', display_name='', anonymized_at=now,
    )
    return affected, drafts, removed_users
