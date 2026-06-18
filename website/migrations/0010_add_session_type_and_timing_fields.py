from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0009_teammembership_race_class'),
    ]

    operations = [
        migrations.AddField(
            model_name='raceclassresultgroup',
            name='session_type',
            field=models.CharField(
                choices=[
                    ('warmup',     'Прогрев'),
                    ('qualifying', 'Квалификация'),
                    ('heat',       'Заезд (ABC)'),
                    ('pre_final',  'Предфинал'),
                    ('final',      'Финал'),
                ],
                default='final',
                max_length=20,
                verbose_name='Тип сессии',
            ),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='start_position',
            field=models.IntegerField(blank=True, null=True, verbose_name='Стартовая позиция'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='best_lap_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Лучший круг, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='best_s1_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Лучший S1, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='best_s2_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Лучший S2, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='best_s3_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Лучший S3, мс'),
        ),
    ]
