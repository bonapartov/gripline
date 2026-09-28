"""Стили и теги писем Gripline — перенос макета «Gripline Emails» (Claude Design).

Письма верстаются таблицами с инлайн-стилями (Gmail/Яндекс Почта режут
<style>, Outlook не понимает flex/grid), поэтому hex-значения токенов
из tokens.css собраны здесь, а шаблоны берут готовые строки через {% s %}.
"""
from django import template
from django.conf import settings
from django.templatetags.static import static
from django.utils.safestring import mark_safe

register = template.Library()

C = {
    'body': '#15151c', 'card': '#1a1a25', 'line': '#2a2a35', 'line2': '#3a3a45',
    'yellow': '#ffc107', 'cyan': '#0dcaf0', 'green': '#28a745', 'red': '#dc3545',
    'fg': '#eceff1', 'fg2': '#b0bec5', 'ink': '#1a1a25', 'white': '#ffffff',
}
FONT = 'Arial, Helvetica, sans-serif'


def font(size, lh, color, extra=''):
    return (f'font-family:{FONT};font-size:{size}px;line-height:{lh}px;'
            f'mso-line-height-rule:exactly;color:{color};{extra}')


LINK = f"color:{C['cyan']};text-decoration:underline;"

STYLES = {
    'h1': 'margin:0;' + font(24, 30, C['fg'], 'font-weight:bold;letter-spacing:0.5px;text-transform:uppercase;'),
    'p': 'margin:0;' + font(16, 24, C['fg']),
    'note': 'margin:0;' + font(14, 21, C['fg2']),
    'fallback': 'margin:0;' + font(12, 18, C['fg2']),
    'footer': font(12, 18, C['fg2']),
    'link': LINK,
    'fallback_link': LINK + 'word-break:break-all;',
    'row_label': font(13, 20, C['fg2']),
    'row_value': font(14, 20, C['fg'], 'font-weight:bold;'),
    'comment_label': 'margin:0 0 6px;' + font(12, 16, C['fg2'], 'font-weight:bold;letter-spacing:1px;text-transform:uppercase;'),
    'comment_text': 'margin:0;' + font(15, 22, C['fg']),
    'admin_tag': font(12, 16, C['fg2'], 'font-weight:bold;letter-spacing:1px;text-transform:uppercase;'),
    'logo_alt': font(22, 28, C['yellow'], 'font-weight:bold;letter-spacing:1px;'),
    'logo_alt_small': font(16, 20, C['yellow'], 'font-weight:bold;letter-spacing:1px;'),
}

# Плашки статуса: (фон, текст, подпись по умолчанию)
STATUS = {
    'ok': (C['green'], C['ink'], 'Одобрено'),
    'bad': (C['red'], C['white'], 'Отклонено'),
    'wait': (C['yellow'], C['ink'], 'На проверке'),
    'info': (C['cyan'], C['ink'], 'Информация'),
}


def _site_url():
    return getattr(settings, 'BASE_URL', 'https://gripline.ru').rstrip('/')


@register.simple_tag
def s(name):
    """Инлайн-стиль по имени: style="{% s 'p' %}"."""
    return mark_safe(STYLES[name])


@register.simple_tag
def c(name):
    return mark_safe(C[name])


@register.simple_tag
def status_style(kind):
    bg, fg, _ = STATUS[kind]
    return mark_safe(f'background-color:{bg};border-radius:4px;padding:5px 10px;'
                     + font(12, 16, fg, 'font-weight:bold;letter-spacing:1px;text-transform:uppercase;'))


@register.simple_tag
def status_bg(kind):
    return mark_safe(STATUS[kind][0])


@register.simple_tag
def status_label(kind):
    return STATUS[kind][2]


@register.simple_tag
def site_url():
    return _site_url()


@register.simple_tag
def email_static(path):
    """Абсолютный URL статики: почтовые клиенты не понимают относительные адреса."""
    return _site_url() + static(path)


def _support():
    from accounts.models import SocialAuthSettings
    try:
        cfg = SocialAuthSettings.get()
        return cfg.contact_email or '', (cfg.telegram_contact or '').strip().lstrip('@')
    except Exception:
        return '', ''


@register.simple_tag
def support_email():
    return _support()[0]


@register.simple_tag
def support_telegram():
    """Ник Telegram поддержки без «@»."""
    return _support()[1]


class RowNode(template.Node):
    def __init__(self, gap, nodelist):
        self.gap, self.nodelist = gap, nodelist

    def render(self, context):
        gap = self.gap.resolve(context)
        return f'<tr><td style="padding:0 0 {gap}px;">{self.nodelist.render(context)}</td></tr>'


@register.tag
def row(parser, token):
    """{% row 16 %}…{% endrow %} — блок письма с нижним отступом (margin в Outlook ненадёжен)."""
    bits = token.split_contents()
    gap = parser.compile_filter(bits[1] if len(bits) > 1 else '16')
    nodelist = parser.parse(('endrow',))
    parser.delete_first_token()
    return RowNode(gap, nodelist)
