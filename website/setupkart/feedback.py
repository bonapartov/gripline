"""Обратная связь из приложения GripLine SetupKart (ТЗ приложения §6.14, §13.2).

Обращение попадает в систему бота обратной связи: канал «приложение» (FeedbackUser.channel),
отдельная категория со своей темой в админ-чате. Ответить пользователю в Telegram нельзя
(в приложении нет входящих сообщений) — только по e-mail, который приходит администратору письмом.
E-mail (ПД) в групповой чат не попадает — как и у остальных обращений.
"""
import logging
import threading

from django.conf import settings
from django.db import connections, transaction
from django.urls import reverse

from website.feedback import service, tg_sync
from website.feedback.notify import _delivery_params
from website.mail import admin_notify_email, send_templated_mail
from website.models import (
    APP_FEEDBACK_CATEGORY_SLUG, FEEDBACK_CHANNEL_SETUPKART, Feedback, FeedbackCategory,
)

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {'bug': 'Ошибка', 'improvement': 'Улучшение', 'feature': 'Новая функция', 'other': 'Другое'}
TEXT_MAX = 5000


def app_category():
    cat, _ = FeedbackCategory.objects.get_or_create(
        slug=APP_FEEDBACK_CATEGORY_SLUG,
        defaults={'title': 'GripLine SetupKart', 'emoji': '📱', 'is_active': False},
    )
    return cat


@transaction.atomic
def create_app_feedback(*, client_id, kind, text, contact_email='', app_version='', device_info=''):
    user = service.get_or_create_user(FEEDBACK_CHANNEL_SETUPKART, client_id)
    answers = {
        'Тип': CATEGORY_LABELS[kind],
        'Сообщение': text,
        'Версия приложения': app_version,
        'Устройство': device_info,
    }
    fb = Feedback.objects.create(
        user=user, category=app_category(),
        answers={k: v for k, v in answers.items() if v},
        admin_note=f'E-mail для ответа: {contact_email}' if contact_email else 'E-mail не указан — ответить нельзя.',
    )
    return fb


def _markup(rows):
    if not rows:
        return None
    return {'inline_keyboard': [[{'text': label, 'callback_data': data} for label, data in row] for row in rows]}


def send_admin_card(fb):
    """Карточка в тему категории админ-чата — в фоне, без ожидания ответа Telegram."""
    from website.feedback.channels.telegram import _card_sync
    try:
        params = _delivery_params()
        if not params:
            return
        body, rows = _card_sync(fb.pk)
        thread_id = fb.category.admin_topic_id if fb.category else None
    except Exception:
        logger.exception('app feedback #%s: карточка не подготовлена', fb.pk)
        return
    token, chat_id, proxy = params

    def run():
        try:
            payload = {'chat_id': chat_id, 'text': body, 'parse_mode': 'HTML',
                       'disable_web_page_preview': True, 'reply_markup': _markup(rows)}
            try:
                msg = tg_sync.api_call(token, 'sendMessage', proxy, {**payload, 'message_thread_id': thread_id})
                used_thread = thread_id
            except tg_sync.TelegramApiError as exc:
                if thread_id and 'thread' in str(exc).lower():
                    msg = tg_sync.api_call(token, 'sendMessage', proxy, payload)
                    used_thread = None
                else:
                    raise
            service.set_admin_card(Feedback.objects.get(pk=fb.pk), msg['message_id'], used_thread)
        except Exception:
            logger.exception('app feedback #%s: карточка в Telegram не отправлена', fb.pk)
        finally:
            # своё соединение фонового потока закрываем, чтобы не копить их у gunicorn-воркера
            if threading.current_thread() is not threading.main_thread():
                connections.close_all()
    threading.Thread(target=run, daemon=True).start()


def send_admin_email(fb, contact_email):
    kind = fb.answers.get('Тип', '')
    subject = f'[GripLine SetupKart] Обратная связь: {kind}'
    try:
        admin_url = f"{settings.BASE_URL.rstrip('/')}{reverse('website_feedback_modeladmin_index')}"
    except Exception:
        admin_url = f"{settings.BASE_URL.rstrip('/')}/admin/"
    rows = [('Номер', f'№{fb.pk}'), ('Тип', kind),
            ('E-mail для ответа', contact_email or 'не указан — ответить нельзя'),
            ('Версия приложения', fb.answers.get('Версия приложения', '')),
            ('Устройство', fb.answers.get('Устройство', ''))]
    try:
        send_templated_mail('admin_app_feedback', subject, [admin_notify_email()], {
            'subject': subject,
            'preheader': f'Обращение №{fb.pk} из приложения: {kind}.',
            'title': f'Обращение №{fb.pk} из приложения',
            'rows': [(k, v) for k, v in rows if v],
            'text': fb.answers.get('Сообщение', ''),
            'admin_url': admin_url,
        }, fail_silently=True)
    except Exception:
        logger.exception('app feedback #%s: письмо не отправлено', fb.pk)


def notify_admins(fb, contact_email):
    send_admin_card(fb)
    send_admin_email(fb, contact_email)


