"""WeasyPrint-обёртка для рендера медиа-кита пилота в PDF.

Движок — WeasyPrint, не headless Chromium/Playwright: VPS без Docker,
gunicorn с 3 воркерами, документ статичный (A4, без JS/интерактивности).
См. CLAUDE.md → «Медиа-кит пилота», раздел 7 ТЗ v1.0.

Шрифты и логотип резолвятся в абсолютные file:// пути через
staticfiles.finders — он всегда видит website/static/ (AppDirectoriesFinder),
независимо от того, был ли уже выполнен collectstatic. Так же не нужен
сетевой поход через nginx на каждую генерацию PDF.
"""
import base64
import io
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from django.contrib.staticfiles import finders
from django.template.loader import render_to_string

# Синхронная генерация без очереди (раздел 7 ТЗ v1.0) — таймаут страхует
# gunicorn-воркер от зависания на медленном/некорректном рендере.
MEDIAKIT_TIMEOUT_SECONDS = 15

# Ключи без дефисов — {{ fonts.InterTight_Light }} в шаблоне: Django-шаблоны
# не умеют разбирать дефис внутри переменной ({{ fonts.InterTight-Light }}
# парсится как вычитание).
FONT_FILES = {
    'InterTight_Light': 'InterTight-Light',
    'InterTight_Regular': 'InterTight-Regular',
    'InterTight_Medium': 'InterTight-Medium',
    'InterTight_SemiBold': 'InterTight-SemiBold',
    'InterTight_Bold': 'InterTight-Bold',
    'InterTight_ExtraBold': 'InterTight-ExtraBold',
    'JetBrainsMono_Regular': 'JetBrainsMono-Regular',
    'JetBrainsMono_Bold': 'JetBrainsMono-Bold',
}

# Хедер — тёмный фон (цветной знак), футер — светлый (приглушённый вариант
# для светлого фона) — см. logo/README.md.
LOGO_ON_DARK_STATIC_PATH = 'website/images/mediakit/gripline-mark-color.svg'
LOGO_ON_LIGHT_STATIC_PATH = 'website/images/mediakit/gripline-mark-color-on-light.svg'
CSS_STATIC_PATH = 'website/css/mediakit-print.css'


class MediakitTimeoutError(Exception):
    """Генерация PDF превысила MEDIAKIT_TIMEOUT_SECONDS."""


def _file_uri(relative_static_path):
    path = finders.find(relative_static_path)
    return f"file://{path}" if path else None


def _static_text(relative_static_path):
    path = finders.find(relative_static_path)
    if not path:
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def _driver_photo_uri(driver):
    if not driver.photo:
        return None
    from wagtail.images.shortcuts import get_rendition_or_not_found

    rendition = get_rendition_or_not_found(driver.photo, 'fill-320x400')
    return f"file://{rendition.file.path}"


def _team_logo_uri(team):
    if not team.logo:
        return None
    from wagtail.images.shortcuts import get_rendition_or_not_found

    rendition = get_rendition_or_not_found(team.logo, 'max-480x480')
    return f"file://{rendition.file.path}"


def _qr_code_data_uri(url):
    import qrcode

    img = qrcode.make(url, box_size=6, border=1)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    encoded = base64.b64encode(buf.getvalue()).decode('ascii')
    return f"data:image/png;base64,{encoded}"


def _render_pdf(template_name, template_context):
    """Общий рендер-пайплайн — шрифты/лого/CSS/таймаут одинаковы для медиа-кита
    пилота и команды, различается только шаблон и специфичный контекст,
    который вызывающая сторона уже подмешала."""
    template_context = {
        **template_context,
        'logo_on_dark_uri': _file_uri(LOGO_ON_DARK_STATIC_PATH),
        'logo_on_light_uri': _file_uri(LOGO_ON_LIGHT_STATIC_PATH),
        'fonts': {key: _file_uri(f'website/fonts/mediakit/{fname}.woff2') for key, fname in FONT_FILES.items()},
        'print_css': _static_text(CSS_STATIC_PATH),
    }

    html_string = render_to_string(template_name, template_context)

    def _render():
        import weasyprint

        return weasyprint.HTML(string=html_string).write_pdf()

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_render)
    try:
        pdf_bytes = future.result(timeout=MEDIAKIT_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        raise MediakitTimeoutError(
            f"Генерация PDF превысила {MEDIAKIT_TIMEOUT_SECONDS} секунд"
        ) from None
    finally:
        executor.shutdown(wait=False)

    return pdf_bytes


def render_mediakit_pdf(context, profile_url_absolute):
    """context — вывод website.services.mediakit.build_mediakit_context().
    profile_url_absolute — канонический URL профиля с доменом (для QR-кода)."""
    driver = context['driver']
    template_context = {
        **context,
        'profile_url_absolute': profile_url_absolute,
        'photo_uri': _driver_photo_uri(driver),
        'qr_code_uri': _qr_code_data_uri(profile_url_absolute),
    }
    return _render_pdf('mediakit/driver_mediakit.html', template_context)


def render_team_mediakit_pdf(context, profile_url_absolute):
    """context — вывод website.services.team_mediakit.build_mediakit_context().
    profile_url_absolute — канонический URL /teams/<slug>/ с доменом (для QR-кода)."""
    team = context['team']
    template_context = {
        **context,
        'profile_url_absolute': profile_url_absolute,
        'logo_uri': _team_logo_uri(team),
        'qr_code_uri': _qr_code_data_uri(profile_url_absolute),
    }
    return _render_pdf('mediakit/team_mediakit.html', template_context)
