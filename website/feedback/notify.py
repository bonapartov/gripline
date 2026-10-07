"""
Служебные уведомления в админ-чат бота обратной связи — не про обращения
бота, а про другие события сайта, которые нельзя пропустить: новое обращение
субъекта ПД (по закону на него 10 рабочих дней) и новая заявка пилота/команды
(см. website/claim_notify.py).

Работает и без запущенного процесса бота: прямой вызов Bot API через
tg_sync (с тем же прокси). Отправка — в фоновом потоке и с коротким
таймаутом: сетевая задержка не должна тормозить ответ пользователю, а сбой
— терять обращение (оно уже в БД). В Telegram уходит только тип, срок и
ссылка на админку — контакт и текст заявителя (ПД) в групповой чат не попадают.
"""
import html
import logging
import threading

from django.conf import settings

from . import tg_sync

logger = logging.getLogger('feedback')

SEND_TIMEOUT = 8


def _delivery_params():
    """(token, chat_id, proxy) или None, если бот не настроен. Читает БД —
    вызывать в основном потоке, не в фоновом."""
    from website.models import FeedbackBotSettings
    cfg = FeedbackBotSettings.get()
    try:
        token = cfg.get_token()
    except Exception:
        logger.exception('Не удалось расшифровать токен бота')
        return None
    if not token or not cfg.admin_chat_id:
        return None
    return token, cfg.admin_chat_id, cfg.proxy_url()


def _send(params, text_html):
    token, chat_id, proxy = params
    try:
        tg_sync.api_call(token, 'sendMessage', proxy, {
            'chat_id': chat_id, 'text': text_html, 'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }, timeout=SEND_TIMEOUT)
    except tg_sync.TelegramApiError as exc:
        logger.warning('Уведомление в админ-чат не отправлено: %s', exc)
        return False
    return True


def send_admin_chat_message(text_html):
    """Синхронно. True — отправлено; False — не настроено или сбой (залогирован без токена)."""
    params = _delivery_params()
    return bool(params) and _send(params, text_html)


def data_request_text(obj):
    base = settings.BASE_URL.rstrip('/')
    url = f'{base}/admin/website/datarequest/edit/{obj.pk}/'
    return (
        f'🔒 <b>Обращение по персональным данным №{obj.pk}</b>\n'
        f'Тип: {html.escape(obj.get_request_type_display())}\n'
        f'Ответить до: <b>{obj.due_date:%d.%m.%Y}</b>\n'
        f'<a href="{html.escape(url, quote=True)}">Открыть в админке</a>'
    )


def notify_admin_chat(text_html, label):
    """Не блокирует запрос и не бросает исключений: БД читается здесь, в фоне —
    только сетевой вызов. `label` — для логов (без ПД)."""
    try:
        params = _delivery_params()
    except Exception:
        logger.exception('%s: уведомление в Telegram не подготовлено', label)
        return
    if not params:
        return

    def run():
        try:
            _send(params, text_html)
        except Exception:
            logger.exception('%s: уведомление в Telegram не отправлено', label)
    threading.Thread(target=run, daemon=True).start()


def notify_data_request(obj):
    try:
        text = data_request_text(obj)
    except Exception:
        logger.exception('data-request #%s: уведомление в Telegram не подготовлено', obj.pk)
        return
    notify_admin_chat(text, f'data-request #{obj.pk}')
