"""View генерации медиа-кита команды (PDF). См. website/services/team_mediakit.py
(контекст), website/services/pdf.py (рендер). Зеркало website/mediakit_views.py
(медиа-кит пилота) — то же самое, владение проверяется через TeamManager
вместо UserProfile.driver.
"""
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from wagtail.models import Site
from wagtailcache.cache import nocache_page

from website.models import Team
from website.services.pdf import MediakitTimeoutError, render_team_mediakit_pdf
from website.services.team_mediakit import build_mediakit_context


def _is_team_manager(request, team):
    """Кнопка/эндпоинт медиа-кита команды — только активному менеджеру этой
    команды (teams.models.TeamManager), не любому авторизованному."""
    if not request.user.is_authenticated:
        return False
    from teams.models import TeamManager

    return TeamManager.objects.filter(user=request.user, team=team, is_active=True).exists()


@nocache_page
def team_mediakit_pdf_view(request, slug):
    """@nocache_page обязателен — wagtailcache подключён глобальным
    middleware и кэширует по URL без учёта пользователя; без декоратора
    первый ответ (даже 403 анонимному) закэшировался бы и обошёл
    owner-гейт для всех следующих посетителей (см. website/mediakit_views.py,
    тот же баг там нашёлся и исправлен на медиа-ките пилота 2026-08-30)."""
    team = get_object_or_404(Team, slug=slug)

    if not _is_team_manager(request, team):
        return HttpResponseForbidden("Медиа-кит доступен только руководителю команды.")

    context = build_mediakit_context(team)

    site = Site.find_for_request(request)
    root_url = site.root_url.rstrip('/') if site else ''
    profile_url_absolute = root_url + team.get_absolute_url()

    try:
        pdf_bytes = render_team_mediakit_pdf(context, profile_url_absolute)
    except MediakitTimeoutError:
        return HttpResponse(
            "Не удалось сформировать PDF за отведённое время — попробуйте ещё раз.",
            status=503,
        )

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="gripline-mediakit-{team.slug}.pdf"'
    return response
