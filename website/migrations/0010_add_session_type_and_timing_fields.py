from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0009_teammembership_race_class'),
    ]

    operations = [
        # --- RaceResult: финал ---
        migrations.AddField(
            model_name='raceresult',
            name='start_position',
            field=models.IntegerField(blank=True, null=True, verbose_name='Стартовая позиция (финал)'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='best_lap_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Лучший круг, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='best_s1_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S1, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='best_s2_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S2, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='best_s3_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S3, мс'),
        ),
        # --- RaceResult: квалификация ---
        migrations.AddField(
            model_name='raceresult',
            name='qual_position',
            field=models.IntegerField(blank=True, null=True, verbose_name='Позиция (квал.)'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='qual_best_lap_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Лучший круг (квал.), мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='qual_s1_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S1 (квал.), мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='qual_s2_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S2 (квал.), мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='qual_s3_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S3 (квал.), мс'),
        ),
        # --- RaceResult: предфинал ---
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_position',
            field=models.IntegerField(blank=True, null=True, verbose_name='Позиция (предфинал)'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_start_pos',
            field=models.IntegerField(blank=True, null=True, verbose_name='Старт (предфинал)'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_best_lap_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Лучший круг (предфинал), мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_s1_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S1 (предфинал), мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_s2_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S2 (предфинал), мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_s3_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S3 (предфинал), мс'),
        ),
    ]
