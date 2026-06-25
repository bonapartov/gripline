from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0012_remove_session_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='raceresult',
            name='qual_position',
            field=models.IntegerField(blank=True, null=True, verbose_name='Позиция'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='qual_best_lap_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Круг, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='qual_s1_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S1, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='qual_s2_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S2, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='qual_s3_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S3, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_position',
            field=models.IntegerField(blank=True, null=True, verbose_name='Позиция'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_start_pos',
            field=models.IntegerField(blank=True, null=True, verbose_name='Старт'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_best_lap_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Круг, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_s1_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S1, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_s2_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S2, мс'),
        ),
        migrations.AddField(
            model_name='raceresult',
            name='pre_final_s3_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S3, мс'),
        ),
    ]
