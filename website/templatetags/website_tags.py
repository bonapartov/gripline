from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Возвращает значение по ключу или пустой словарь"""
    return dictionary.get(key, {})

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
