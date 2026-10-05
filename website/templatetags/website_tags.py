from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def breadcrumb_schema(context):
    """
    JSON-LD BreadcrumbList. Берёт готовый список из контекста (breadcrumb_items —
    для view без Wagtail-страницы, например driver_page.html) либо строит его
    из page.get_ancestors() для обычных Wagtail-страниц.
    """
    from website.schema import build_breadcrumb_items, breadcrumb_list_dict, render_json_ld

    items = context.get('breadcrumb_items')
    if not items:
        page = context.get('page') or context.get('self')
        items = build_breadcrumb_items(page)

    return render_json_ld(breadcrumb_list_dict(items))

@register.filter
def get_item(dictionary, key):
    """Возвращает значение по ключу или None"""
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def pluralize_ru(value, arg):
    """Склонение существительных после числительных в русском языке
    Использование: {{ value|pluralize_ru:"гонка,гонки,гонок" }}
    """
    try:
        value = int(value)
        forms = arg.split(',')
        if len(forms) != 3:
            return f"{value}"

        if value % 10 == 1 and value % 100 != 11:
            return f"{value} {forms[0]}"
        elif 2 <= value % 10 <= 4 and (value % 100 < 10 or value % 100 >= 20):
            return f"{value} {forms[1]}"
        else:
            return f"{value} {forms[2]}"
    except (ValueError, TypeError):
        return str(value)

@register.filter
def get_type(value):
    """Возвращает тип объекта для отладки"""
    return type(value).__name__

@register.filter
def pprint(value):
    """Красивый вывод для отладки"""
    import pprint
    return pprint.pformat(value)

@register.filter
def month_name_ru(date_value):
    """Преобразует дату в русское название месяца"""
    months_ru = {
        1: 'Январь',
        2: 'Февраль',
        3: 'Март',
        4: 'Апрель',
        5: 'Май',
        6: 'Июнь',
        7: 'Июль',
        8: 'Август',
        9: 'Сентябрь',
        10: 'Октябрь',
        11: 'Ноябрь',
        12: 'Декабрь'
    }

    if hasattr(date_value, 'month'):
        month_num = date_value.month
        year = date_value.year
        return f"{months_ru[month_num]} {year}"

    return str(date_value)


@register.simple_tag
def get_organizer_settings():
    try:
        from organizers.models import OrganizerSettings
        return OrganizerSettings.objects.first()
    except Exception:
        return None

@register.filter
def get_item(dictionary, key):
    """Возвращает значение по ключу или None"""
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def pluralize_ru(value, arg):
    """Склонение существительных после числительных в русском языке
    Использование: {{ value|pluralize_ru:"гонка,гонки,гонок" }}
    """
    try:
        value = int(value)
        forms = arg.split(',')
        if len(forms) != 3:
            return f"{value}"

        if value % 10 == 1 and value % 100 != 11:
            return f"{value} {forms[0]}"
        elif 2 <= value % 10 <= 4 and (value % 100 < 10 or value % 100 >= 20):
            return f"{value} {forms[1]}"
        else:
            return f"{value} {forms[2]}"
    except (ValueError, TypeError):
        return str(value)

@register.filter
def get_type(value):
    """Возвращает тип объекта для отладки"""
    return type(value).__name__

@register.filter
def pprint(value):
    """Красивый вывод для отладки"""
    import pprint
    return pprint.pformat(value)

@register.filter
def month_name_ru(date_value):
    """Преобразует дату в русское название месяца"""
    months_ru = {
        1: 'Январь',
        2: 'Февраль',
        3: 'Март',
        4: 'Апрель',
        5: 'Май',
        6: 'Июнь',
        7: 'Июль',
        8: 'Август',
        9: 'Сентябрь',
        10: 'Октябрь',
        11: 'Ноябрь',
        12: 'Декабрь'
    }

    if hasattr(date_value, 'month'):
        month_num = date_value.month
        year = date_value.year
        return f"{months_ru[month_num]} {year}"

    return str(date_value)


@register.simple_tag
def get_social_auth_settings():
    try:
        from accounts.models import SocialAuthSettings
        return SocialAuthSettings.get()
    except Exception:
        return None


@register.filter
def laptime(ms):
    """62347 → '1:02.347'"""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return '—'
    minutes = ms // 60000
    seconds = (ms % 60000) / 1000
    return f"{minutes}:{seconds:06.3f}"


@register.filter
def ru_word(value, arg):
    """Только слово в нужной форме, без числа: {{ n|ru_word:"старт,старта,стартов" }}"""
    try:
        n = abs(int(value))
        forms = arg.split(',')
        if len(forms) != 3:
            return ''
        if n % 10 == 1 and n % 100 != 11:
            return forms[0]
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return forms[1]
        return forms[2]
    except (ValueError, TypeError):
        return ''


@register.simple_tag(takes_context=True)
def site_footers(context):
    """Футеры (сниппеты CodeRed), подключённые к сайту, с непустым содержимым. Пустой список —
    шаблон footer.html показывает встроенный запасной футер."""
    from coderedcms.models import Footer, LayoutSettings
    request = context.get('request')
    if request is None:
        return []
    layout = LayoutSettings.for_request(request)
    ordered = Footer.objects.filter(
        footerorderable__in=layout.site_footer.all()
    ).order_by('footerorderable__sort_order')
    return [f for f in ordered if f.content]
