"""
Анонс-постинг статей (Матчасть, Новости) в Telegram-канал Gripline.

Токен бота — только в переменной окружения TELEGRAM_ANNOUNCE_BOT_TOKEN,
никогда в БД/админке (см. website/models.py::TelegramSettings — там только
channel_id и оформление тегов, не секрет).
"""
import html
import logging
import os

import requests
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import TelegramSettings, TelegramTag

logger = logging.getLogger('telegram_announce')

REQUEST_TIMEOUT = 10  # секунд — не давать админ-запросу зависнуть, если Telegram API недоступен
CAPTION_LIMIT = 1024  # лимит Telegram на подпись к фото
MESSAGE_LIMIT = 4096  # лимит Telegram на текстовое сообщение (без фото)


def get_category_tag_for_page(page):
    """Тег, чей parent_page совпадает с фактическим родителем статьи — его
    эмодзи используется как баннер перед заголовком поста. Если таких
    тегов несколько — берём первый по алфавиту (детерминированно)."""
    parent = page.get_parent()
    return TelegramTag.objects.filter(parent_page_id=parent.id).order_by('tag').first()


def get_auto_tags_for_page(page):
    """Теги без родительской страницы (публикуются на всех постах) + теги,
    у которых parent_page совпадает с фактическим родителем этой статьи."""
    parent = page.get_parent()
    return list(
        TelegramTag.objects.filter(Q(parent_page__isnull=True) | Q(parent_page_id=parent.id)).order_by('tag')
    )


def get_active_tags_for_page(page):
    """Все теги поста: автоматические (по родительской странице/без неё) +
    вручную добавленные на самой статье, без дублей. Публикуются все сразу."""
    auto_tags = get_auto_tags_for_page(page)
    auto_ids = {t.pk for t in auto_tags}
    manual_tags = [t for t in page.telegram_extra_tags.all() if t.pk not in auto_ids]
    return auto_tags + manual_tags


def get_message_overhead(page):
    """Длина всего в сообщении, кроме самого тизера и вручную добавленных на
    статье тегов: эмодзи, заголовок статьи, автоматические теги, текст
    ссылки и служебные переводы строк. Вручную добавленные теги не входят —
    их длина считается на клиенте (см. live-счётчик в Wagtail Admin), т.к.
    выбор в мультиселекте меняется без перезагрузки страницы. URL ссылки в
    подсчёт не входит — Telegram считает длину уже после подстановки
    видимого текста <a> и <b>, не href."""
    category_tag = get_category_tag_for_page(page)
    emoji = category_tag.emoji if category_tag else ''
    auto_tags = get_auto_tags_for_page(page)
    tag_line = ' '.join((f"{t.emoji} {t.tag}" if t.emoji else t.tag) for t in auto_tags)
    link_text = TelegramSettings.get().link_text
    # +6: пробел после эмодзи, \n\n после заголовка, \n\n перед тегами, \n перед ссылкой
    return len(emoji) + len(page.title) + len(tag_line) + len(link_text) + 6


def build_telegram_message(page):
    """Собирает текст сообщения. telegram_teaser — свободный ввод редактора,
    обязательно экранируется перед вставкой в HTML-разметку Telegram."""
    category_tag = get_category_tag_for_page(page)
    emoji = html.escape(category_tag.emoji) if category_tag and category_tag.emoji else ''
    tags = get_active_tags_for_page(page)
    tag_line = ' '.join(
        (f"{html.escape(t.emoji)} {html.escape(t.tag)}" if t.emoji else html.escape(t.tag))
        for t in tags
    )
    # UTM-слаг — по слагу фактической родительской страницы, не по хардкоду
    # типа страницы: новый раздел сайта получит свой campaign автоматически.
    campaign = page.get_parent().slug

    url = f"https://gripline.ru{page.url}?utm_source=telegram&utm_medium=social&utm_campaign={campaign}"
    # Ссылка через <a href> с коротким текстом — иначе Telegram показывает
    # длинный percent-encoded URL (кириллический slug) прямо в тексте поста.
    link_text = TelegramSettings.get().link_text
    link = f'<a href="{html.escape(url)}">{html.escape(link_text)}</a>'

    safe_title = html.escape(page.title)
    safe_teaser = html.escape(page.telegram_teaser)
    text = f"{emoji} <b>{safe_title}</b>\n\n{safe_teaser}\n\n{tag_line}\n{link}".strip()
    return text


def send_to_telegram(page, requesting_user):
    """Отправляет анонс страницы в канал. Синхронно — вызывающая сторона
    (кнопка в Wagtail Admin) сама показывает результат администратору."""
    telegram_settings = TelegramSettings.get()
    message = build_telegram_message(page)
    image = getattr(page, 'cover_image', None)
    # Прокси нужен там, где хостер блокирует прямые соединения к Telegram
    # (см. settings.TELEGRAM_PROXY_URL). Локально не задан — идём напрямую.
    proxies = {"https": settings.TELEGRAM_PROXY_URL} if settings.TELEGRAM_PROXY_URL else None

    try:
        if image and len(message) <= CAPTION_LIMIT:
            rendition = image.get_rendition('width-1200')
            # Файл грузим напрямую (multipart), не по URL — Telegram сам
            # скачивает по URL со своих серверов, а это ненадёжно (недоступно
            # с localhost при локальной разработке, и не гарантированно
            # достижимо для прода любым хостингом/сетью).
            with rendition.file.open('rb') as f:
                resp = requests.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_ANNOUNCE_BOT_TOKEN}/sendPhoto",
                    data={
                        "chat_id": telegram_settings.channel_id,
                        "caption": message,
                        "parse_mode": "HTML",
                    },
                    files={"photo": (os.path.basename(rendition.file.name), f)},
                    proxies=proxies,
                    timeout=REQUEST_TIMEOUT,
                )
        else:
            # Нет картинки, либо сообщение длиннее лимита подписи (1024) —
            # отправляем текстом без фото (лимит sendMessage — 4096).
            # Текст тизера никогда не обрезается молча.
            resp = requests.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_ANNOUNCE_BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": telegram_settings.channel_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                proxies=proxies,
                timeout=REQUEST_TIMEOUT,
            )
        resp.raise_for_status()
    except requests.RequestException as e:
        # Никогда не логировать токен бота или тело ответа Telegram без фильтрации.
        logger.error("Telegram send failed for page %s: %s", page.pk, type(e).__name__)
        raise

    page.telegram_posted_at = timezone.now()
    page.telegram_posted_by = requesting_user
    page.save(update_fields=['telegram_posted_at', 'telegram_posted_by'])

    logger.info(
        "Telegram announce sent: page=%s user=%s",
        page.pk, requesting_user.username,
    )
    return resp.json()
