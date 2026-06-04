from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0007_analytics_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='analyticssettings',
            name='trend_window',
            field=models.IntegerField(
                default=5,
                help_text='Число гонок для расчёта тренда. Сравниваются последние N и предыдущие N гонок. Минимум стартов для показа тренда = N+1.',
                verbose_name='Окно тренда формы (гонок)',
            ),
        ),
    ]
