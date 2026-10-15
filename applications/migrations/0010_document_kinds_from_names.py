"""Типы документов по названию: «Мед справка» → «Медицинская справка» и т.п.
Название постоянного типа задаёт тип (см. applications/document_kinds.py)."""
from django.db import migrations

from applications import document_kinds


def forwards(apps, schema_editor):
    for model in ('StageDocument', 'ChampionshipDocument'):
        for doc in apps.get_model('applications', model).objects.all():
            kind = document_kinds.kind_by_name(doc.name)
            if kind == document_kinds.OTHER:
                continue
            doc.kind = kind
            doc.name, doc.minors_only = document_kinds.FIXED[kind]
            doc.has_expiry_date = True
            doc.save(update_fields=['kind', 'name', 'minors_only', 'has_expiry_date'])
    PilotDocument = apps.get_model('accounts', 'PilotDocument')
    for doc in PilotDocument.objects.all():
        kind = document_kinds.kind_by_name(doc.name)
        if kind != document_kinds.OTHER:
            doc.kind, doc.name = kind, document_kinds.label(kind)
            doc.save(update_fields=['kind', 'name'])


class Migration(migrations.Migration):
    dependencies = [
        ('applications', '0009_documentremindersettings_and_more'),
        ('accounts', '0013_pilotdocument_kind_pilotdocument_rejected_at_and_more'),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
