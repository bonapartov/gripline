"""
Синхронные вызовы Bot API для админки (проверка соединения, тест чата,
создание тем). Через requests — как website/telegram.py. Токен не попадает
ни в исключения, ни в ответы: любая ошибка очищается от него перед показом.
"""
import requests

TIMEOUT = 15


class TelegramApiError(Exception):
    pass


def _clean(text, token):
    return str(text).replace(token, '***') if token else str(text)


def api_call(token, method, proxy_url=None, payload=None, timeout=TIMEOUT):
    if not token:
        raise TelegramApiError('Токен бота не задан.')
    proxies = {'https': proxy_url, 'http': proxy_url} if proxy_url else None
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/{method}',
            json=payload or {}, proxies=proxies, timeout=timeout,
        )
    except requests.RequestException as exc:
        raise TelegramApiError(f'Нет соединения с Telegram: {_clean(exc, token)[:300]}') from None
    try:
        data = resp.json()
    except ValueError:
        raise TelegramApiError(f'Неожиданный ответ Telegram (HTTP {resp.status_code}).') from None
    if not data.get('ok'):
        raise TelegramApiError(f'Telegram: {_clean(data.get("description", "ошибка"), token)}')
    return data['result']


def check_connection(cfg):
    """getMe через заданный прокси → юзернейм бота."""
    me = api_call(cfg.get_token(), 'getMe', cfg.proxy_url())
    return me


def send_test_message(cfg):
    if not cfg.admin_chat_id:
        raise TelegramApiError('ID админ-чата не задан.')
    return api_call(cfg.get_token(), 'sendMessage', cfg.proxy_url(), {
        'chat_id': cfg.admin_chat_id,
        'text': '✅ Тест: бот обратной связи Gripline подключён к этому чату.',
    })


def create_category_topics(cfg):
    """Тема на каждую активную категорию без admin_topic_id. Возвращает
    (создано, [ошибки]). Нужны супергруппа с включёнными темами и право
    бота «Управление темами»."""
    from django.db.models import Q
    from website.models import APP_FEEDBACK_CATEGORY_SLUG, FeedbackCategory
    if not cfg.admin_chat_id:
        raise TelegramApiError('ID админ-чата не задан.')
    created, errors = 0, []
    # категория приложения неактивна (её нет в меню бота), но тема ей нужна
    for cat in FeedbackCategory.objects.filter(
            Q(is_active=True) | Q(slug=APP_FEEDBACK_CATEGORY_SLUG), admin_topic_id__isnull=True):
        try:
            topic = api_call(cfg.get_token(), 'createForumTopic', cfg.proxy_url(), {
                'chat_id': cfg.admin_chat_id,
                'name': f'{cat.emoji} {cat.title}'.strip()[:128],
            })
        except TelegramApiError as exc:
            errors.append(f'{cat.title}: {exc}')
            continue
        cat.admin_topic_id = topic['message_thread_id']
        cat.save(update_fields=['admin_topic_id'])
        created += 1
    return created, errors
