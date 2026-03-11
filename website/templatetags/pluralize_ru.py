from django import template

register = template.Library()

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
