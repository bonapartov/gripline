from django.db import migrations, models


def set_three_races(apps, schema_editor):
    # Agreed threshold is three distinct result groups, not five result rows.
    settings = apps.get_model('website', 'AnalyticsSettings')
    settings.objects.using(schema_editor.connection.alias).update(min_races_per_class=3)


class Migration(migrations.Migration):
    dependencies = [('website', '0109_track_page_settings')]

    operations = [
        migrations.AlterField(
            model_name='analyticssettings', name='min_races_per_class',
            field=models.IntegerField(
                default=3, verbose_name='Мин. заездов для расчёта класса',
                help_text='Число отдельных групп результатов класса с допущенными результатами, не число пилотов. По умолчанию 3; дополнительно проверяется минимум сравнений.',
            ),
        ),
        migrations.RunPython(set_three_races, migrations.RunPython.noop),
    ]
