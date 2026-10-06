"""Подсказки категорий для виджета «Обратная связь» (заполняются только если пусто — правки админа не затираются)."""
from django.db import migrations

HINTS = {
    'data-error': 'Неточность в данных на странице',
    'add-object': 'Трасса, клуб или этап, которых нет на сайте',
    'suggestion': 'Что добавить или улучшить',
    'partnership': 'Реклама, партнёрство, сотрудничество',
    'other': 'Любой другой вопрос',
}


def fill(apps, schema_editor):
    Category = apps.get_model('website', 'FeedbackCategory')
    for slug, hint in HINTS.items():
        Category.objects.filter(slug=slug, widget_hint='').update(widget_hint=hint)


class Migration(migrations.Migration):
    dependencies = [('website', '0050_feedbackcategory_widget_hint')]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
