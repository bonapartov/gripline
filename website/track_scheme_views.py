"""Схема трассы: PDF A4 на сайте и редактор схемы в админке.

Редактор (чистый JS + SVG, website/static/website/js/track_scheme_editor.js) присылает
только числа — опорные точки, доли длины для старта и границ секторов, повороты. Сервер
проверяет их (track_scheme.clean_scheme_data) и сам строит SVG — разметка из браузера на
сайт не попадает. Схема сохраняется сразу на сайт (решение владельца 23.10.2026).

Подложка для обводки (scheme_reference) лежит в закрытом хранилище (PRIVATE_MEDIA_ROOT)
и отдаётся только редактору с правом change_track.
"""
import hashlib
import json

import filetype
from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from wagtail.log_actions import log
from wagtail.models import Site
from wagtailcache.cache import nocache_page

from website.models import Track
from website.services import track_scheme
from website.services.pdf import MediakitTimeoutError, render_track_scheme_pdf

PERM = 'website.change_track'
REFERENCE_MAX_BYTES = 15 * 1024 * 1024
REFERENCE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
PDF_CACHE_SECONDS = 60 * 60 * 24 * 30
# Менять при правке макета листа (шаблон/CSS) — иначе из кэша отдаётся старый PDF
PDF_LAYOUT_VERSION = 3


def _address(track):
    return ', '.join(x for x in (track.region, track.city, track.address) if x)


# ── PDF ──────────────────────────────────────────────────────────────────

def _pdf_cache_key(track):
    """Меняется при правке схемы и всего, что печатается на листе."""
    parts = [PDF_LAYOUT_VERSION, track.pk, track.name, _address(track), track.length_m, track.app_direction,
             track.effective_turns_count, track.scheme_updated_at.isoformat() if track.scheme_updated_at else '']
    return 'track-scheme-pdf:' + hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()


@nocache_page
def track_scheme_pdf_view(request, slug):
    """/tracks/<slug>/scheme.pdf. Свой кэш (по содержимому), не wagtailcache — тот не знает,
    когда схема поменялась."""
    track = get_object_or_404(Track, slug=slug)
    if not track.has_scheme:
        raise Http404('У трассы нет схемы')

    key = _pdf_cache_key(track)
    pdf_bytes = cache.get(key)
    if pdf_bytes is None:
        site = Site.find_for_request(request)
        root = site.root_url.rstrip('/') if site else ''
        context = {
            'track': track,
            'address': _address(track),
            'turns_count': track.effective_turns_count,
            'scheme_svg': mark_safe(track_scheme.render_svg(
                track.scheme_data, palette='print', aria_label='Схема трассы для печати', length_m=track.length_m)),
            'turn_ranges': track_scheme.sector_turn_ranges(track.scheme_data),
            'scheme_osm': track_scheme.is_osm(track.scheme_data),
        }
        try:
            pdf_bytes = render_track_scheme_pdf(context, root + track.get_absolute_url())
        except MediakitTimeoutError:
            return HttpResponse('Не удалось сформировать PDF за отведённое время — попробуйте ещё раз.', status=503)
        cache.set(key, pdf_bytes, PDF_CACHE_SECONDS)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="gripline-{track.slug}-skhema.pdf"'
    return response


# ── Редактор (админка) ───────────────────────────────────────────────────

def _check(request):
    if not request.user.has_perm(PERM):
        return HttpResponseForbidden('Нет права редактировать трассы')
    return None


def editor(request, pk):
    denied = _check(request)
    if denied:
        return denied
    track = get_object_or_404(Track, pk=pk)
    return render(request, 'track_scheme/editor.html', {
        'track': track,
        'editor_data': {
            'scheme': track.scheme_data,
            'length_m': float(track.length_m) if track.length_m else None,
            'direction': track.app_direction or None,
            'has_reference': bool(track.scheme_reference),
        },
    })


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return None


@require_POST
def editor_preview(request, pk):
    """SVG схемы, каким его увидит сайт, — для вкладки предпросмотра."""
    denied = _check(request)
    if denied:
        return denied
    track = get_object_or_404(Track, pk=pk)
    try:
        data = track_scheme.clean_scheme_data(_json_body(request), length_m=track.length_m)
    except track_scheme.SchemeError as e:
        return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({
        'svg': track_scheme.render_svg(data, aria_label=track_scheme.aria_label(track, data), length_m=track.length_m),
        'turn_ranges': track_scheme.sector_turn_ranges(data),
        'labels': track_scheme.label_positions(data, length_m=track.length_m),
        'widths': track_scheme.stroke_widths(data, length_m=track.length_m),
        'public': track_scheme.public_scheme(data),
    })


@require_POST
def editor_save(request, pk):
    denied = _check(request)
    if denied:
        return denied
    track = get_object_or_404(Track, pk=pk)
    try:
        data = track_scheme.clean_scheme_data(_json_body(request), length_m=track.length_m)
    except track_scheme.SchemeError as e:
        return JsonResponse({'error': str(e)}, status=400)
    track.scheme_data = data
    track.scheme_svg = track_scheme.render_svg(data, aria_label=track_scheme.aria_label(track, data),
                                               length_m=track.length_m)
    track.scheme_updated_at = timezone.now()
    # post_save сбрасывает кэш страницы трассы (website/signals.py)
    track.save(update_fields=['scheme_data', 'scheme_svg', 'scheme_updated_at'])
    log(instance=track, action='wagtail.edit', user=request.user, data={'scheme': True})
    return JsonResponse({
        'ok': True,
        'saved_at': timezone.localtime(track.scheme_updated_at).strftime('%d.%m.%Y %H:%M'),
        'published': track.has_scheme,
        'draft': track.scheme_is_draft,
    })


@require_POST
def editor_clear(request, pk):
    """Удалить схему с сайта (подложка остаётся)."""
    denied = _check(request)
    if denied:
        return denied
    track = get_object_or_404(Track, pk=pk)
    track.scheme_data = None
    track.scheme_svg = ''
    track.scheme_updated_at = timezone.now()
    track.save(update_fields=['scheme_data', 'scheme_svg', 'scheme_updated_at'])
    log(instance=track, action='wagtail.edit', user=request.user, data={'scheme': 'cleared'})
    return JsonResponse({'ok': True})


def editor_reference(request, pk):
    """GET — отдать подложку; POST — загрузить новую (или удалить: action=delete)."""
    denied = _check(request)
    if denied:
        return denied
    track = get_object_or_404(Track, pk=pk)
    if request.method == 'GET':
        if not track.scheme_reference:
            raise Http404()
        f = track.scheme_reference.open('rb')
        kind = filetype.guess(f.read(262))
        f.seek(0)
        response = FileResponse(f, content_type=kind.mime if kind else 'application/octet-stream')
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    if request.method != 'POST':
        return HttpResponse(status=405)

    if request.POST.get('action') == 'delete':
        if track.scheme_reference:
            track.scheme_reference.delete(save=False)
        track.scheme_reference = ''
        track.save(update_fields=['scheme_reference'])
        return JsonResponse({'ok': True})

    upload = request.FILES.get('file')
    if not upload:
        return JsonResponse({'error': 'Файл не выбран'}, status=400)
    if upload.size > REFERENCE_MAX_BYTES:
        return JsonResponse({'error': 'Файл больше 15 МБ'}, status=400)
    kind = filetype.guess(upload.read(262))
    upload.seek(0)
    if not kind or kind.mime not in REFERENCE_TYPES:
        return JsonResponse({'error': 'Нужна картинка JPG, PNG или WebP'}, status=400)
    if track.scheme_reference:
        track.scheme_reference.delete(save=False)
    track.scheme_reference.save(f'{track.pk}-{timezone.now():%Y%m%d%H%M%S}.{kind.extension}', upload, save=False)
    track.save(update_fields=['scheme_reference'])
    return JsonResponse({'ok': True})


def sector_time_shares(track):
    """Доли S1/S2/S3 во времени круга по всем классам трассы с секторами (средние, с весом по стартам)."""
    from website.services import track_stats
    classes = [c for c in track_stats.build_track_classes(track_stats.load_rows(track)) if c['has_sectors']]
    if not classes:
        return None, [], None
    weight = sum(c['starts'] for c in classes)
    shares = [sum(c['sectors'][k]['ms'] / c['ideal_ms'] * c['starts'] for c in classes) / weight for k in range(3)]
    return shares, [c['name'] for c in classes], max(classes, key=lambda c: c['starts'])


@require_POST
def editor_auto_bounds(request, pk):
    """Границы S1|S2 и S2|S3 по реальным временам секторов (модель скорости — как у 3D-метки)."""
    denied = _check(request)
    if denied:
        return denied
    track = get_object_or_404(Track, pk=pk)
    if not track.length_m:
        return JsonResponse({'error': 'Укажите длину трассы в карточке — без неё скорость не посчитать'}, status=400)
    try:
        data = track_scheme.clean_scheme_data(_json_body(request), length_m=track.length_m)
    except track_scheme.SchemeError as e:
        return JsonResponse({'error': str(e)}, status=400)
    shares, names, main = sector_time_shares(track)
    if not shares:
        return JsonResponse({'error': 'На этой трассе нет результатов с временами секторов'}, status=400)
    from website.services.track_page import top_speed_kmh
    # модель скорости — как у 3D-метки самого массового класса (его максимальная скорость и рекорд)
    s1s2, s2s3 = track_scheme.bounds_by_sector_times(
        data, track.length_m, shares, top_kmh=top_speed_kmh(main['name']), lap_sec=main['record']['ms'] / 1000)
    return JsonResponse({'s1s2': s1s2, 's2s3': s2s3, 'shares': [round(x * 100, 1) for x in shares], 'classes': names})
