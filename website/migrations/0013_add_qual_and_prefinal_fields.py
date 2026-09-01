from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Изначально все 11 операций были AddField — но эти же 11 колонок уже
    добавила 0010_add_session_type_and_timing_fields (баг: два AddField на
    каждое поле подряд, только verbose_name отличался — "Позиция (квал.)"
    vs "Позиция" и т.п.). На реальных БД (dev/prod) это давно "применено"
    (django_migrations просто помнит номер миграции, SQL повторно не
    выполняется — правка файла там ничего не меняет), но на чистой БД
    (тестовая БД pytest-django, свежий clone) повторный AddField падал с
    "column already exists" на первом же из 11 полей. Заменено на AlterField
    — финализирует verbose_name к текущему виду в модели (без суффиксов
    "(квал.)"/"(предфинал)" — контекст уже понятен из имени поля).
    """

    dependencies = [
        ('website', '0012_remove_session_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='raceresult',
            name='qual_position',
            field=models.IntegerField(blank=True, null=True, verbose_name='Позиция'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='qual_best_lap_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Круг, мс'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='qual_s1_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S1, мс'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='qual_s2_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S2, мс'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='qual_s3_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S3, мс'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='pre_final_position',
            field=models.IntegerField(blank=True, null=True, verbose_name='Позиция'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='pre_final_start_pos',
            field=models.IntegerField(blank=True, null=True, verbose_name='Старт'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='pre_final_best_lap_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='Круг, мс'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='pre_final_s1_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S1, мс'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='pre_final_s2_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S2, мс'),
        ),
        migrations.AlterField(
            model_name='raceresult',
            name='pre_final_s3_ms',
            field=models.IntegerField(blank=True, null=True, verbose_name='S3, мс'),
        ),
    ]
