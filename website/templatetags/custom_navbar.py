from django import template
from django.template.loader import render_to_string

register = template.Library()

@register.simple_tag(takes_context=True)
def custom_navbar_buttons(context):
    """Рендерит кастомные кнопки для навбара"""
    request = context.get('request')
    user = request.user if request else None

    return render_to_string('coderedcms/snippets/navbar_custom.html', {
        'user': user,
    }, request=request)
