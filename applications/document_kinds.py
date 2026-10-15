"""
Постоянные типы документов участника.

У постоянного типа название не меняется от этапа к этапу, поэтому документ, загруженный
в заявку, сохраняется в ЛК пилота (accounts.PilotDocument) и подставляется в следующие
заявки по типу, а не по названию. «Другой» — документ с названием от организатора, в ЛК
не сохраняется.

Модуль без импорта моделей: его используют и applications, и accounts.
"""

OTHER = 'other'
LICENSE = 'license'
POWER_OF_ATTORNEY = 'power_of_attorney'
INSURANCE = 'insurance'
MEDICAL = 'medical'

# код -> (название, только для несовершеннолетних)
FIXED = {
    LICENSE: ('Лицензия', False),
    POWER_OF_ATTORNEY: ('Доверенность', True),
    INSURANCE: ('Страховка', False),
    MEDICAL: ('Медицинская справка', False),
}

CHOICES = [(code, label) for code, (label, _) in FIXED.items()] + [(OTHER, 'Другой документ')]
VAULT_CHOICES = [(code, label) for code, (label, _) in FIXED.items()] + [(OTHER, 'Другой')]

# Старые названия → тип (миграция данных и документы ЛК, загруженные до типов).
NAME_ALIASES = {
    'лицензия': LICENSE, 'лицензия пилота': LICENSE, 'спортивная лицензия': LICENSE,
    'доверенность': POWER_OF_ATTORNEY, 'нотариальная доверенность': POWER_OF_ATTORNEY,
    'страховка': INSURANCE, 'страховой полис': INSURANCE, 'страхование': INSURANCE,
    'медсправка': MEDICAL, 'мед справка': MEDICAL, 'мед. справка': MEDICAL,
    'медицинская справка': MEDICAL, 'медицинский допуск': MEDICAL,
}


def is_fixed(kind):
    return kind in FIXED


def label(kind):
    return FIXED[kind][0] if kind in FIXED else ''


def kind_by_name(name):
    return NAME_ALIASES.get(' '.join((name or '').lower().split()), OTHER)


def apply_fixed(doc):
    """Документ этапа/чемпионата постоянного типа: название, «только несовершеннолетние»
    и срок действия задаются типом, а не организатором."""
    if doc.kind in FIXED:
        doc.name, doc.minors_only = FIXED[doc.kind]
        doc.has_expiry_date = True
