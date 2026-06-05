from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizers', '0008_championship_tyre_mode_stage_tyres'),
    ]

    operations = [
        migrations.AddField(
            model_name='championship',
            name='registration_mode',
            field=models.CharField(
                choices=[('per_stage', 'Настройки для каждого этапа отдельно'), ('all', 'Общие настройки для всех этапов')],
                default='per_stage',
                max_length=20,
                verbose_name='Режим настроек регистрации',
            ),
        ),
    ]
