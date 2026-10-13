"""13.10.2026: «Супер-мини» и «Супер-мини ГР-3» — детское шасси (подтвердил владелец).
Класс X30 Mini («только для приложения») с двигателем IAME Swift 60 — Swift снова показывается в приложении
(скрыт 10.10 как дубль). Минимальный вес X30 Mini не заполнен — внести в «Классы гонок».
"""
from django.db import migrations


def seed(apps, schema_editor):
    RaceClass = apps.get_model('website', 'RaceClass')
    Engine = apps.get_model('website', 'Engine')
    RaceClass.objects.filter(name__in=['Супер-мини', 'Супер-мини ГР-3'], chassis_type='').update(chassis_type='junior')
    x30_mini = RaceClass.objects.filter(name='X30 Mini').first()
    if x30_mini is None:
        x30_mini = RaceClass.objects.create(name='X30 Mini', app_only=True, chassis_type='junior', sort_order=890)
    swift = Engine.objects.filter(name='IAME Swift 60').first()
    if swift is not None:
        swift.show_in_app = True
        swift.save(update_fields=['show_in_app'])
        swift.app_race_classes.add(x30_mini)


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0098_app_float_models_rok_seed'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
