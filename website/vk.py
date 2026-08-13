"""
Анонс-постинг статей (Матчасть, Новости) в сообщество VK Gripline.

Токен доступа — только в переменной окружения VK_ANNOUNCE_ACCESS_TOKEN,
никогда в БД/админке (см. website/models.py::VkSettings — там только
group_id и текст ссылки, не секрет).

VK доступен с прод-сервера напрямую — прокси не нужен (см. website/telegram.py
и TELEGRAM_PROXY_URL — там ситуация другая).

В отличие от Telegram/MAX, VK Wall API не поддерживает HTML/Markdown в
тексте поста — message собирается как plain text, кликабельная ссылка
делается встроенным VK-синтаксисом *url (текст)*.
"""
import logging
import os

import requests
from django.conf import settings
from django.utils import timezone

from .models import VkSettings
from .social_tags import get_active_tags_for_page, get_auto_tags_for_page, get_category_tag_for_page

logger = logging.getLogger('vk_announce')

REQUEST_TIMEOUT = 10  # секунд — не давать админ-запросу зависнуть, если VK API недоступен
VK_TEXT_LIMIT = 4070  # лимит VK на текст поста — уточнить эмпирически перед продом
VK_API_BASE_URL = "https://api.vk.com/method"


def _vk_call(method, params):
    """POST-вызов метода VK API. VK возвращает HTTP 200 даже при ошибках
    API — сама ошибка лежит внутри JSON-тела в ключе 'error', это нужно
    проверять отдельно от HTTP-статуса."""
    payload = dict(params)
    payload.setdefault('access_token', settings.VK_ANNOUNCE_ACCESS_TOKEN)
    payload.setdefault('v', settings.VK_API_VERSION)
    resp = requests.post(f"{VK_API_BASE_URL}/{method}", data=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if 'error' in data:
        error = data['error']
        raise requests.RequestException(
            f"VK API error in {method}: code={error.get('error_code')} msg={error.get('error_msg')}"
        )
    return data['response']


def _build_vk_link(page):
    """VK-текст не поддерживает HTML — ссылка с произвольным текстом делается
    встроенным синтаксисом *url (текст)*, где сам URL пишется в теле
    сообщения целиком (не спрятан в href, как у Telegram/MAX), поэтому его
    длина тоже входит в лимит текста, не только текст ссылки."""
    campaign = page.get_parent().slug
    url = f"https://gripline.ru{page.url}?utm_source=vk&utm_medium=social&utm_campaign={campaign}"
    link_text = VkSettings.get().link_text
    return f"*{url} ({link_text})*"


def get_vk_message_overhead(page):
    """Длина всего в сообщении, кроме самого тизера и вручную добавленных на
    статье тегов — см. website/max.py::get_max_message_overhead, логика
    идентична. Один лимит (VK_TEXT_LIMIT), без ветвления has_image/no_image —
    как у MAX, картинка и текст у VK тоже уходят одним вызовом."""
    category_tag = get_category_tag_for_page(page)
    emoji = category_tag.emoji if category_tag else ''
    auto_tags = get_auto_tags_for_page(page)
    tag_line = ' '.join((f"{t.emoji} {t.tag}" if t.emoji else t.tag) for t in auto_tags)
    link = _build_vk_link(page)
    # +4: пробел после эмодзи, \n\n после заголовка, \n\n перед тегами, \n перед ссылкой
    return len(emoji) + len(page.title) + len(tag_line) + len(link) + 4


def build_vk_message(page):
    """Собирает текст поста. social_teaser — общий с Telegram/MAX, свободный
    ввод редактора. Никакого html.escape — VK-текст plain text, не HTML."""
    category_tag = get_category_tag_for_page(page)
    emoji = category_tag.emoji if category_tag else ''
    tags = get_active_tags_for_page(page)
    tag_line = ' '.join((f"{t.emoji} {t.tag}" if t.emoji else t.tag) for t in tags)
    link = _build_vk_link(page)

    title_line = f"{emoji} {page.title}".strip()
    text = f"{title_line}\n\n{page.social_teaser}\n\n{tag_line}\n{link}".strip()
    return text


def _get_wall_upload_url(group_id):
    """Шаг 1 загрузки фото: спросить у VK адрес CDN-эндпоинта для загрузки."""
    response = _vk_call('photos.getWallUploadServer', {'group_id': group_id})
    return response['upload_url']


def _upload_photo_bytes(upload_url, rendition):
    """Шаг 2: сама загрузка файла (multipart, поле 'photo') на CDN-адрес.
    Ответ этого запроса — НЕ через стандартный конверт VK API (нет ключа
    'response'), это отдельный CDN-сервис, отдаёт {server, photo, hash}
    напрямую. Файл грузим напрямую из rendition, не по URL — тем же
    обоснованием, что у Telegram/MAX (недоступность файла для внешнего
    скачивания на localhost/непредсказуемых хостингах)."""
    with rendition.file.open('rb') as f:
        resp = requests.post(
            upload_url,
            files={"photo": (os.path.basename(rendition.file.name), f)},
            timeout=REQUEST_TIMEOUT,
        )
    resp.raise_for_status()
    return resp.json()


def _save_wall_photo(group_id, upload_result):
    """Шаг 3: сохранить загруженное фото за сообществом, получить итоговый
    объект фото с owner_id/id для вложения."""
    response = _vk_call('photos.saveWallPhoto', {
        'group_id': group_id,
        'photo': upload_result['photo'],
        'server': upload_result['server'],
        'hash': upload_result['hash'],
    })
    photo = response[0]
    return f"photo{photo['owner_id']}_{photo['id']}"


def upload_image_to_vk(image, group_id):
    """Оркестрирует трёхэтапную загрузку, возвращает строку вложения вида
    'photo<owner_id>_<id>' для attachments в wall.post."""
    rendition = image.get_rendition('width-1200')
    upload_url = _get_wall_upload_url(group_id)
    upload_result = _upload_photo_bytes(upload_url, rendition)
    return _save_wall_photo(group_id, upload_result)


def send_to_vk(page, requesting_user):
    """Публикует анонс страницы на стену сообщества VK. Синхронно —
    вызывающая сторона (кнопка в Wagtail Admin) сама показывает результат
    администратору."""
    vk_settings = VkSettings.get()
    message = build_vk_message(page)
    image = getattr(page, 'cover_image', None)
    attachments = []

    try:
        if image:
            try:
                attachments.append(upload_image_to_vk(image, vk_settings.group_id))
            except requests.RequestException:
                # Ключ доступа сообщества не умеет photos.* (error 27,
                # "method is unavailable with group auth") — для фото нужен
                # user-токен через OAuth, которого пока нет. До готовности
                # публикуем без фото вместо падения целиком.
                logger.warning(
                    "VK photo upload failed for page %s, falling back to text-only post",
                    page.pk,
                )

        response = _vk_call('wall.post', {
            'owner_id': f"-{vk_settings.group_id}",
            'from_group': 1,
            'message': message,
            'attachments': ",".join(attachments),
        })
    except requests.RequestException as e:
        # Никогда не логировать токен доступа или сырое тело ответа VK без фильтрации.
        logger.error("VK send failed for page %s: %s", page.pk, type(e).__name__)
        raise

    page.vk_posted_at = timezone.now()
    page.vk_posted_by = requesting_user
    page.save(update_fields=['vk_posted_at', 'vk_posted_by'])

    logger.info(
        "VK announce sent: page=%s user=%s",
        page.pk, requesting_user.username,
    )
    return response
