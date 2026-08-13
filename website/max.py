"""
Анонс-постинг статей (Матчасть, Новости) в канал MAX Gripline.

Токен бота — только в переменной окружения MAX_ANNOUNCE_BOT_TOKEN, никогда
в БД/админке (см. website/models.py::MaxSettings — там только chat_id и
текст ссылки, не секрет).

В отличие от Telegram, MAX доступен с прод-сервера напрямую — прокси не
нужен (см. website/telegram.py::send_to_telegram и TELEGRAM_PROXY_URL).
"""
import html
import logging
import os

import requests
from django.conf import settings
from django.utils import timezone

from .models import MaxSettings
from .social_tags import get_active_tags_for_page, get_auto_tags_for_page, get_category_tag_for_page

logger = logging.getLogger('max_announce')

REQUEST_TIMEOUT = 10  # секунд — не давать админ-запросу зависнуть, если MAX API недоступен
MAX_TEXT_LIMIT = 4000  # лимит MAX на текст сообщения — уточнить эмпирически перед продом


def get_max_message_overhead(page):
    """Длина всего в сообщении, кроме самого тизера и вручную добавленных на
    статье тегов — см. website/telegram.py::get_message_overhead, логика
    идентична. У MAX нет отдельного лимита подписи к фото — картинка и
    текст уходят одним вызовом, поэтому здесь только один лимит
    (MAX_TEXT_LIMIT), без ветвления has_image/no_image."""
    category_tag = get_category_tag_for_page(page)
    emoji = category_tag.emoji if category_tag else ''
    auto_tags = get_auto_tags_for_page(page)
    tag_line = ' '.join((f"{t.emoji} {t.tag}" if t.emoji else t.tag) for t in auto_tags)
    link_text = MaxSettings.get().link_text
    # +6: пробел после эмодзи, \n\n после заголовка, \n\n перед тегами, \n перед ссылкой
    return len(emoji) + len(page.title) + len(tag_line) + len(link_text) + 6


def build_max_message(page):
    """Собирает текст сообщения. social_teaser — общий с Telegram, свободный
    ввод редактора, обязательно экранируется перед вставкой в HTML-разметку
    (format="html" при отправке — см. send_to_max)."""
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

    url = f"https://gripline.ru{page.url}?utm_source=max&utm_medium=social&utm_campaign={campaign}"
    link_text = MaxSettings.get().link_text
    link = f'<a href="{html.escape(url)}">{html.escape(link_text)}</a>'

    safe_title = html.escape(page.title)
    safe_teaser = html.escape(page.social_teaser)
    text = f"{emoji} <b>{safe_title}</b>\n\n{safe_teaser}\n\n{tag_line}\n{link}".strip()
    return text


def _request_max_upload_url():
    """Шаг 1 загрузки картинки: спросить у platform-api адрес CDN-эндпоинта
    для загрузки. Возвращает url — сам он уже содержит авторизацию в
    query-строке, отдельный Authorization-заголовок на шаге 2 не нужен."""
    resp = requests.post(
        f"{settings.MAX_API_BASE_URL}/uploads",
        params={"type": "image"},
        headers={"Authorization": settings.MAX_ANNOUNCE_BOT_TOKEN},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["url"]


def _upload_image_bytes(upload_url, rendition):
    """Шаг 2: сама загрузка файла (multipart, поле 'data') на CDN-адрес,
    полученный на шаге 1. Файл грузим напрямую из rendition, не по URL —
    тем же обоснованием, что и у Telegram (недоступность файла для
    внешнего скачивания на localhost/непредсказуемых хостингах)."""
    with rendition.file.open('rb') as f:
        resp = requests.post(
            upload_url,
            files={"data": (os.path.basename(rendition.file.name), f)},
            timeout=REQUEST_TIMEOUT,
        )
    resp.raise_for_status()
    # Ответ — не плоский {"token": ...}, а {"photos": {"<photoId>": {"token": ...}}},
    # где photoId — внутренний идентификатор, выданный на шаге 1 (в upload_url) и
    # не нужный дальше. Грузим всегда ровно один файл за вызов — берём единственное
    # значение словаря. Подтверждено реальным вызовом MAX API (2026-08-13).
    photos = resp.json()["photos"]
    return next(iter(photos.values()))["token"]


def upload_image_to_max(image):
    """Оркестрирует двухэтапную загрузку, возвращает финальный token для
    вложения в сообщение."""
    rendition = image.get_rendition('width-1200')
    upload_url = _request_max_upload_url()
    return _upload_image_bytes(upload_url, rendition)


def send_to_max(page, requesting_user):
    """Отправляет анонс страницы в канал MAX. Синхронно — вызывающая сторона
    (кнопка в Wagtail Admin) сама показывает результат администратору.

    В отличие от Telegram — один вызов POST /messages для текста и картинки
    сразу, нет разделения sendPhoto/sendMessage и разных лимитов на каждый
    случай."""
    max_settings = MaxSettings.get()
    text = build_max_message(page)
    image = getattr(page, 'cover_image', None)
    attachments = []

    try:
        if image:
            token = upload_image_to_max(image)
            attachments.append({"type": "image", "payload": {"token": token}})

        resp = requests.post(
            f"{settings.MAX_API_BASE_URL}/messages",
            params={"chat_id": max_settings.chat_id},
            json={
                "text": text,
                "attachments": attachments,
                "format": "html",
                "notify": True,
            },
            headers={"Authorization": settings.MAX_ANNOUNCE_BOT_TOKEN},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        # Никогда не логировать токен бота или тело ответа MAX без фильтрации.
        logger.error("MAX send failed for page %s: %s", page.pk, type(e).__name__)
        raise

    page.max_posted_at = timezone.now()
    page.max_posted_by = requesting_user
    page.save(update_fields=['max_posted_at', 'max_posted_by'])

    logger.info(
        "MAX announce sent: page=%s user=%s",
        page.pk, requesting_user.username,
    )
    return resp.json()
