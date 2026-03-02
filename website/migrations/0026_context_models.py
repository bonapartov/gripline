# Generated manually
# Миграция для добавления полей контекстной модели

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0025_ensemble_models'),
    ]

    operations = [
        # Добавляем поля для контекстной модели в Driver
        migrations.AddField(
            model_name='driver',
            name='context_by_class',
            field=models.JSONField(blank=True, default=dict, help_text="Формат: {'class_id': {'score': 0.75, 'starts': 5}}", verbose_name='Context-Aware по классам'),
        ),
        migrations.AddField(
            model_name='driver',
            name='context_score',
            field=models.FloatField(default=0.0, help_text='Брэдли-Терри с учётом погоды и шин', verbose_name='Рейтинг (Context-Aware)'),
        ),
        migrations.AddField(
            model_name='driver',
            name='context_updated_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Дата обновления контекстной модели'),
        ),
        migrations.AddField(
            model_name='driver',
            name='context_weights',
            field=models.JSONField(blank=True, default=dict, help_text="Формат: {'temperature': 0.5, 'precipitation': -0.3, 'tyre': 0.2, 'track': 0.1}", verbose_name='Веса контекстных факторов'),
        ),
    ]
