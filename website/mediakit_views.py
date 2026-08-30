"""View генерации медиа-кита пилота (PDF).

Отдельный модуль, а не website/views.py (тот уже 3000+ строк, единый модуль
без пакета) — см. CLAUDE.md → «Медиа-кит пилота». Логика — в
website/services/mediakit.py (контекст) и website/services/pdf.py (рендер).
"""
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from wagtail.models import Site
from wagtailcache.cache import nocache_page

from website.models import Driver
from website.services.mediakit import build_mediakit_context
from website.services.pdf import MediakitTimeoutError, render_mediakit_pdf


def _is_mediakit_owner(request, driver):
    """Кнопка/эндпоинт медиа-кита — только владельцу профиля («в личном
    кабинете пилота», раздел 3 ТЗ v1.0), с подтверждённой администратором
    привязкой (UserProfile.verified) — как и остальные владелец-only действия
    в проекте (см. accounts.models.UserProfile)."""
    if not request.user.is_authenticated:
        return False
    profile = getattr(request.user, 'profile', None)
    if not profile:
        return False
    return profile.driver_id == driver.id and profile.verified


@nocache_page
def driver_mediakit_pdf_view(request, slug):
    """Персонализированный, owner-gated эндпоинт — @nocache_page обязателен:
    wagtailcache подключён глобальным middleware (UpdateCacheMiddleware +
    FetchFromCacheMiddleware, mysite/settings/base.py), кэширует по URL без
    учёта пользователя/сессии. Без декоратора первый ответ на этот URL
    (даже 403 анонимному) закэшируется и будет отдан всем следующим
    посетителям — включая обход owner-гейта. WAGTAIL_CACHE=False в dev.py
    ровно для этого эндпоинта отключён локально, поэтому баг не проявлялся
    ни разу при разработке — найден только при первой проверке на проде."""
    driver = get_object_or_404(Driver, slug=slug)

    if not _is_mediakit_owner(request, driver):
        return HttpResponseForbidden("Медиа-кит доступен только владельцу профиля пилота.")

    context = build_mediakit_context(driver)

    site = Site.find_for_request(request)
    root_url = site.root_url.rstrip('/') if site else ''
    profile_url_absolute = root_url + driver.get_absolute_url()

    try:
        pdf_bytes = render_mediakit_pdf(context, profile_url_absolute)
    except MediakitTimeoutError:
        return HttpResponse(
            "Не удалось сформировать PDF за отведённое время — попробуйте ещё раз.",
            status=503,
        )

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="gripline-mediakit-{driver.slug}.pdf"'
    return response
