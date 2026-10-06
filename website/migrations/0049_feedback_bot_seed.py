"""Стартовые данные бота обратной связи: категории, шаги, тексты (ТЗ gripline_tz_feedback_bot_v1)."""
from django.db import migrations

CATEGORIES = [
    # slug, title, emoji, sort, deep_link_code
    ('data-error', 'Ошибка в данных', '🐞', 10, 'err'),
    ('add-object', 'Добавить трассу / клуб / этап', '➕', 20, 'add'),
    ('suggestion', 'Предложение', '💡', 30, 'idea'),
    ('partnership', 'Сотрудничество / реклама', '🤝', 40, 'biz'),
    ('other', 'Другое', '💬', 50, 'other'),
]

# slug категории -> шаги: (key, prompt, type, required, skip_text, skip_if_source_set)
STEPS = {
    'data-error': [
        ('where', 'Где ошибка? Укажите страницу, этап, пилота или ссылку.', 'text', True, '', True),
        ('what', 'Что не так? Опишите, как должно быть.', 'text', True, '', False),
        ('screenshot', 'Приложите скриншот, если есть (лучше отправить как файл — без сжатия).', 'attachment', False, 'Пропустить', False),
    ],
    'add-object': [
        ('name', 'Как называется трасса, клуб или этап?', 'text', True, '', False),
        ('city', 'В каком городе?', 'text', True, '', False),
        ('link', 'Ссылка на сайт или соцсети.', 'text', False, 'Пропустить', False),
        ('contact', 'Как с вами связаться, если понадобятся уточнения?', 'text', False, 'Пропустить', False),
    ],
    'suggestion': [
        ('text', 'Расскажите, что стоит добавить или улучшить.', 'text', True, '', False),
    ],
    'partnership': [
        ('text', 'Расскажите о предложении.', 'text', True, '', False),
        ('contact', 'Как с вами связаться?', 'text', True, '', False),
    ],
    'other': [
        ('text', 'Напишите, что хотите сообщить.', 'text', True, '', False),
    ],
}


def seed(apps, schema_editor):
    from website.feedback.texts import DEFAULT_TEXTS
    Category = apps.get_model('website', 'FeedbackCategory')
    Step = apps.get_model('website', 'FeedbackStep')
    Text = apps.get_model('website', 'FeedbackText')
    Settings = apps.get_model('website', 'FeedbackBotSettings')

    Settings.objects.get_or_create(pk=1)
    for slug, title, emoji, sort, code in CATEGORIES:
        cat, _ = Category.objects.get_or_create(
            slug=slug,
            defaults={'title': title, 'emoji': emoji, 'sort_order': sort, 'deep_link_code': code},
        )
        for i, (key, prompt, typ, required, skip, skip_src) in enumerate(STEPS[slug], start=1):
            Step.objects.get_or_create(
                category=cat, key=key,
                defaults={
                    'sort_order': i * 10, 'prompt_text': prompt, 'type': typ,
                    'is_required': required, 'skip_button_text': skip,
                    'skip_if_source_set': skip_src,
                },
            )
    for key, (text, description) in DEFAULT_TEXTS.items():
        Text.objects.get_or_create(key=key, defaults={'text': text, 'description': description})


class Migration(migrations.Migration):
    dependencies = [('website', '0048_feedback_bot')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
