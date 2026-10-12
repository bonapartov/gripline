"""Развесовка /balance/: классы — RaceClass вместо отдельного справочника KartClass.

Тип шасси и геометрия класса переезжают на RaceClass, Setup.kart_class → Setup.race_class,
KartClass удаляется. На момент миграции (12.10.2026) ни KartClass, ни Setup на проде нет —
данные не переносятся; если сетапы всё же есть, миграция остановится, а не потеряет их.
"""
import django.db.models.deletion
from django.db import migrations, models


def ensure_no_setups(apps, schema_editor):
    Setup = apps.get_model('website', 'Setup')
    if Setup.objects.exists():
        raise RuntimeError(
            'Есть сохранённые сетапы развесовки — перенос kart_class → race_class не написан. '
            'Нужна миграция данных по названию класса.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0081_app_chassis_params'),
    ]

    operations = [
        migrations.RunPython(ensure_no_setups, migrations.RunPython.noop),
        migrations.AddField(
            model_name='raceclass',
            name='chassis_type',
            field=models.CharField(blank=True, choices=[('junior', 'Детское'), ('senior', 'Взрослое')], help_text='Для калькулятора развесовки на сайте: класс доступен только картам этого типа. Пусто — любым картам.', max_length=10, verbose_name='Тип шасси (развесовка)'),
        ),
        migrations.AddField(
            model_name='raceclass',
            name='wheelbase_mm',
            field=models.PositiveIntegerField(blank=True, help_text='Развесовка: переопределение пресета типа шасси. Пусто — берётся пресет.', null=True, verbose_name='Колёсная база, мм'),
        ),
        migrations.AddField(
            model_name='raceclass',
            name='track_front_mm',
            field=models.PositiveIntegerField(blank=True, help_text='Развесовка: переопределение пресета типа шасси. Пусто — берётся пресет.', null=True, verbose_name='Колея перед, мм'),
        ),
        migrations.AddField(
            model_name='raceclass',
            name='track_rear_mm',
            field=models.PositiveIntegerField(blank=True, help_text='Развесовка: переопределение пресета типа шасси. Пусто — берётся пресет.', null=True, verbose_name='Колея зад, мм'),
        ),
        migrations.RemoveField(
            model_name='setup',
            name='kart_class',
        ),
        migrations.AddField(
            model_name='setup',
            name='race_class',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='balance_setups', to='website.raceclass', verbose_name='Класс'),
        ),
        migrations.AlterField(
            model_name='setup',
            name='race_class',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='balance_setups', to='website.raceclass', verbose_name='Класс'),
        ),
        migrations.DeleteModel(
            name='KartClass',
        ),
    ]
