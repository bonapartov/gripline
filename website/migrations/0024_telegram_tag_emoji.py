from django.db import migrations, models


def seed_emoji_from_settings(apps, schema_editor):
    """Переносит emoji_matchast/emoji_news из TelegramSettings на теги,
    привязанные к соответствующим родительским страницам (Матчасть/Новости) —
    после переноса поле emoji живёт на самом теге, а не в настройках."""
    TelegramSettings = apps.get_model('website', 'TelegramSettings')
    TelegramTag = apps.get_model('website', 'TelegramTag')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    settings_obj = TelegramSettings.objects.first()
    if not settings_obj:
        return

    def tags_for_page_type(model_name):
        try:
            ct = ContentType.objects.get(app_label='website', model=model_name)
        except ContentType.DoesNotExist:
            return TelegramTag.objects.none()
        return TelegramTag.objects.filter(parent_page__content_type=ct)

    emoji_matchast = getattr(settings_obj, 'emoji_matchast', '')
    if emoji_matchast:
        tags_for_page_type('techarticleindexpage').update(emoji=emoji_matchast)

    emoji_news = getattr(settings_obj, 'emoji_news', '')
    if emoji_news:
        tags_for_page_type('articleindexpage').update(emoji=emoji_news)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0023_telegram_tags'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramtag',
            name='emoji',
            field=models.CharField(blank=True, help_text='Например: 🔧. Необязательно, показывается перед тегом в посте.', max_length=8, verbose_name='Эмодзи'),
        ),
        migrations.RunPython(seed_emoji_from_settings, noop_reverse),
        migrations.RemoveField(
            model_name='telegramsettings',
            name='emoji_matchast',
        ),
        migrations.RemoveField(
            model_name='telegramsettings',
            name='emoji_news',
        ),
    ]
