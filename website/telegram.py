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
from django.utils import timezone

from .models import ArticleIndexPage, TechArticleIndexPage, TelegramSettings

logger = logging.getLogger('telegram_announce')

REQUEST_TIMEOUT = 10  # секунд — не давать админ-запросу зависнуть, если Telegram API недоступен
CAPTION_LIMIT = 1024  # лимит Telegram на подпись к фото
MESSAGE_LIMIT = 4096  # лимит Telegram на текстовое сообщение (без фото)


def get_telegram_settings_for_page(page):
    """Тег и эмодзи для страницы — по родителю (Матчасть/Новости), не по классу.

    ArticlePage — единый класс и для новостей, и для статей матчасти,
    различаются только родительской страницей.
    """
    telegram_settings = TelegramSettings.get()
    parent = page.get_parent().specific

    if isinstance(parent, TechArticleIndexPage):
        return telegram_settings.tag_matchast, telegram_settings.emoji_matchast
    if isinstance(parent, ArticleIndexPage):
        return telegram_settings.tag_news, telegram_settings.emoji_news

    return '', ''


def get_message_overhead(page):
    """Длина всего в сообщении, кроме самого тизера: эмодзи, тег, текст ссылки
    и служебные переводы строк. URL ссылки в подсчёт не входит — Telegram
    считает длину уже после подстановки видимого текста <a>, не href.
    Используется live-счётчиком символов тизера в Wagtail Admin."""
    tag, emoji = get_telegram_settings_for_page(page)
    link_text = TelegramSettings.get().link_text
    return len(emoji) + len(tag) + len(link_text) + 4  # +4: пробел, \n\n, \n


def build_telegram_message(page):
    """Собирает текст сообщения. telegram_teaser — свободный ввод редактора,
    обязательно экранируется перед вставкой в HTML-разметку Telegram."""
    tag, emoji = get_telegram_settings_for_page(page)
    campaign = tag.lstrip('#')

    url = f"https://gripline.ru{page.url}?utm_source=telegram&utm_medium=social&utm_campaign={campaign}"
    # Ссылка через <a href> с коротким текстом — иначе Telegram показывает
    # длинный percent-encoded URL (кириллический slug) прямо в тексте поста.
    link_text = TelegramSettings.get().link_text
    link = f'<a href="{html.escape(url)}">{html.escape(link_text)}</a>'

    safe_teaser = html.escape(page.telegram_teaser)
    text = f"{emoji} {safe_teaser}\n\n{tag}\n{link}".strip()
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
