from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizers', '0007_championship_default_tyres'),
        ('website', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='championship',
            name='tyre_mode',
            field=models.CharField(
                choices=[('all', 'Одни шины для всех этапов'), ('per_stage', 'Шины на каждый этап отдельно')],
                default='all',
                max_length=20,
                verbose_name='Режим назначения шин',
            ),
        ),
        migrations.AddField(
            model_name='stage',
            name='stage_tyres',
            field=models.ManyToManyField(
                blank=True,
                help_text="Шины для этого этапа (если в чемпионате режим 'per_stage')",
                related_name='stages',
                to='website.tyre',
            ),
        ),
    ]
