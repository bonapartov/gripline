from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Возвращает значение по ключу или пустой словарь"""
    return dictionary.get(key, {})
