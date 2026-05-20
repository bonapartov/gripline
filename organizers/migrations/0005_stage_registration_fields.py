from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizers', '0004_championship_default_tyre_championship_race_classes'),
    ]

    operations = [
        migrations.AddField(
            model_name='stage',
            name='registration_enabled',
            field=models.BooleanField(default=True, verbose_name='Регистрация открыта'),
        ),
        migrations.AddField(
            model_name='stage',
            name='registration_deadline',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Дедлайн регистрации'),
        ),
        migrations.AddField(
            model_name='stage',
            name='late_registration_allowed',
            field=models.BooleanField(default=False, verbose_name='Допустить позднюю регистрацию'),
        ),
        migrations.AddField(
            model_name='stage',
            name='late_registration_fee_multiplier',
            field=models.DecimalField(decimal_places=2, default=2.0, max_digits=4, verbose_name='Множитель позднего взноса'),
        ),
        migrations.AddField(
            model_name='stage',
            name='max_participants',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Макс. участников'),
        ),
        migrations.AddField(
            model_name='stage',
            name='start_number_digits',
            field=models.PositiveIntegerField(choices=[(2, '2-значные (10–99)'), (3, '3-значные (100–999)')], default=2, verbose_name='Формат стартовых номеров'),
        ),
        migrations.AddField(
            model_name='stage',
            name='reserved_start_numbers',
            field=models.JSONField(blank=True, default=list, help_text='Номера недоступные для выбора участниками (JSON-список)', verbose_name='Зарезервированные номера'),
        ),
    ]
