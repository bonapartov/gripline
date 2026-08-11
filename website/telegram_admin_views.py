"""
Admin-эндпоинты для кнопки «Отправить в Telegram» на странице статьи в Wagtail Admin.
Сама логика сборки/отправки сообщения — в website/telegram.py.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from wagtail.models import Page

from .models import ArticlePage
from .telegram import send_to_telegram

DOUBLE_CLICK_GUARD_SECONDS = 10


def _get_article_or_none(page_id):
    page = get_object_or_404(Page, pk=page_id).specific
    return page if isinstance(page, ArticlePage) else None


@login_required
def telegram_status(request, page_id):
    """Данные для рендера кнопки: применимо ли к этой странице, можно ли слать сейчас."""
    article = _get_article_or_none(page_id)
    if article is None:
        return JsonResponse({"applicable": False})

    can_publish = article.permissions_for_user(request.user).can_publish()

    return JsonResponse({
        "applicable": True,
        "teaser_filled": bool(article.telegram_teaser),
        "live": article.live,
        "posted_at": article.telegram_posted_at.isoformat() if article.telegram_posted_at else None,
        "can_publish": can_publish,
    })


@login_required
def telegram_send(request, page_id):
    """Отправка анонса статьи в Telegram-канал. Синхронно, с полной серверной
    ревалидацией всех guard-условий (клиентские проверки — только для UX)."""
    if request.method != 'POST':
        return JsonResponse({"success": False, "message": "Метод не поддерживается"}, status=405)

    article = _get_article_or_none(page_id)
    if article is None:
        return JsonResponse({"success": False, "message": "Страница не найдена"}, status=404)

    if not article.permissions_for_user(request.user).can_publish():
        return JsonResponse({"success": False, "message": "Нет прав на публикацию этой страницы"}, status=403)

    if not article.telegram_teaser:
        return JsonResponse({"success": False, "message": "Заполните тизер для Telegram"}, status=400)

    if not article.live:
        return JsonResponse({"success": False, "message": "Страница ещё не опубликована"}, status=400)

    if article.telegram_posted_at:
        seconds_since = (timezone.now() - article.telegram_posted_at).total_seconds()
        if seconds_since < DOUBLE_CLICK_GUARD_SECONDS:
            return JsonResponse({"success": False, "message": "Уже отправлено только что — подождите немного"}, status=429)

    try:
        send_to_telegram(article, request.user)
    except Exception:
        return JsonResponse({"success": False, "message": "Ошибка отправки в Telegram — проверьте логи"}, status=502)

    return JsonResponse({"success": True, "message": "Отправлено в Telegram-канал"})
