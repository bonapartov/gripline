import django.db.models.deletion
import modelcluster.fields
from django.db import migrations, models


def seed_tags_from_settings(apps, schema_editor):
    """Переносит существующие tag_matchast/tag_news из TelegramSettings в
    новую модель TelegramTag, привязывая их к фактическим родительским
    страницам (Матчасть/Новости) — чтобы после удаления старых полей
    поведение постинга не изменилось."""
    TelegramSettings = apps.get_model('website', 'TelegramSettings')
    TelegramTag = apps.get_model('website', 'TelegramTag')
    Page = apps.get_model('wagtailcore', 'Page')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    settings_obj = TelegramSettings.objects.first()
    if not settings_obj:
        return

    def first_page_of_type(model_name):
        try:
            ct = ContentType.objects.get(app_label='website', model=model_name)
        except ContentType.DoesNotExist:
            return None
        return Page.objects.filter(content_type=ct).first()

    tag_matchast = getattr(settings_obj, 'tag_matchast', '')
    if tag_matchast:
        TelegramTag.objects.get_or_create(
            tag=tag_matchast,
            defaults={'parent_page': first_page_of_type('techarticleindexpage')},
        )

    tag_news = getattr(settings_obj, 'tag_news', '')
    if tag_news:
        TelegramTag.objects.get_or_create(
            tag=tag_news,
            defaults={'parent_page': first_page_of_type('articleindexpage')},
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0022_add_telegram_link_text'),
        ('wagtailcore', '0096_referenceindex_referenceindex_source_object_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TelegramTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tag', models.CharField(help_text='Например: #юниоры', max_length=32, verbose_name='Тег')),
                ('parent_page', models.ForeignKey(blank=True, help_text='Родительская страница, в которой должны быть статьи, чтобы получить этот тег (например, Матчасть или Новости). Если не выбрана — тег публикуется на всех постах.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='telegram_tags', to='wagtailcore.page', verbose_name='Раздел')),
            ],
            options={
                'verbose_name': 'Тег Telegram',
                'verbose_name_plural': 'Теги Telegram',
                'ordering': ['parent_page', 'tag'],
            },
        ),
        migrations.RunPython(seed_tags_from_settings, noop_reverse),
        migrations.AddField(
            model_name='articlepage',
            name='telegram_extra_tags',
            field=modelcluster.fields.ParentalManyToManyField(blank=True, help_text='Добавляются к автоматическим тегам раздела для этого конкретного поста.', to='website.telegramtag', verbose_name='Доп. теги для Telegram'),
        ),
        migrations.RemoveField(
            model_name='telegramsettings',
            name='tag_matchast',
        ),
        migrations.RemoveField(
            model_name='telegramsettings',
            name='tag_news',
        ),
    ]
