from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0025_add_max_settings_and_fields'),
    ]

    operations = [
        migrations.RenameField(
            model_name='articlepage',
            old_name='telegram_teaser',
            new_name='social_teaser',
        ),
        migrations.AlterField(
            model_name='articlepage',
            name='social_teaser',
            field=models.TextField(
                blank=True,
                help_text=(
                    'Короткий тизер для анонса в соцсетях (Telegram, MAX и др.), 3–5 '
                    'предложений. Лимит ~900 символов — оставляет запас под ссылку, '
                    'теги и подпись к фото (самый тесный из лимитов площадок — '
                    'подпись к фото в Telegram, 1024 символа).'
                ),
                max_length=900,
                verbose_name='Тизер для соцсетей',
            ),
        ),
    ]
