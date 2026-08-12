import django.db.models.deletion
import modelcluster.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0026_rename_teaser_to_social'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='TelegramTag',
            new_name='SocialTag',
        ),
        migrations.AlterModelOptions(
            name='socialtag',
            options={
                'ordering': ['parent_page', 'tag'],
                'verbose_name': 'Тег соцсетей',
                'verbose_name_plural': 'Теги соцсетей',
            },
        ),
        migrations.AlterField(
            model_name='socialtag',
            name='parent_page',
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    'Родительская страница, в которой должны быть статьи, чтобы получить '
                    'этот тег (например, Матчасть или Новости). Если не выбрана — тег '
                    'публикуется на всех постах.'
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='social_tags',
                to='wagtailcore.page',
                verbose_name='Раздел',
            ),
        ),
        migrations.RenameField(
            model_name='articlepage',
            old_name='telegram_extra_tags',
            new_name='social_extra_tags',
        ),
        migrations.AlterField(
            model_name='articlepage',
            name='social_extra_tags',
            field=modelcluster.fields.ParentalManyToManyField(
                blank=True,
                help_text='Добавляются к автоматическим тегам раздела для этого конкретного поста — во всех соцсетях сразу.',
                to='website.socialtag',
                verbose_name='Доп. теги для соцсетей',
            ),
        ),
    ]
