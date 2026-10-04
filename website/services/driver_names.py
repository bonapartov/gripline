"""
Сопоставление ФИО пилотов при импорте: «Артем» = «Артём», «Журавлев» = «Журавлёв»,
латинская «c» внутри русского слова («Ленcкий») = кириллическая «с».

Тире, пробелы и «й»/«и» намеренно не нормализуются — только е/ё и латинские
двойники кириллицы.
"""
import re

from ..models import Driver

# Латинские буквы, визуально неотличимые от кириллических.
_LATIN_TO_CYRILLIC = str.maketrans({
    'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К', 'M': 'М',
    'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У',
    'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х', 'y': 'у',
})
_CYRILLIC = re.compile(r'[А-Яа-яЁё]')
_WORD = re.compile(r'\S+')


def clean_name(value):
    """Обрезает пробелы и заменяет латинские двойники на кириллицу — только в словах,
    где уже есть кириллица (чисто латинские имена, например иностранные, не трогаем)."""
    value = re.sub(r'\s+', ' ', (value or '').strip())

    def fix(match):
        word = match.group(0)
        return word.translate(_LATIN_TO_CYRILLIC) if _CYRILLIC.search(word) else word

    return _WORD.sub(fix, value)


def name_key(value):
    """Ключ для сравнения: без регистра, ё = е, латинские двойники = кириллица."""
    return clean_name(value).casefold().replace('ё', 'е')


def find_drivers_by_name(first_name, last_name):
    """Все пилоты с таким же ФИО по правилам name_key (список, порядок по id)."""
    first_key, last_key = name_key(first_name), name_key(last_name)
    if not first_key or not last_key:
        return []
    ids = [
        pk for pk, first, last in Driver.objects.values_list('id', 'first_name', 'last_name')
        if name_key(first) == first_key and name_key(last) == last_key
    ]
    return list(Driver.objects.filter(id__in=ids).order_by('id')) if ids else []
