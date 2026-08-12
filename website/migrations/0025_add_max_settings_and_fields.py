import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0024_telegram_tag_emoji'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MaxSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chat_id', models.CharField(blank=True, help_text="Числовой ID канала MAX. В отличие от Telegram, у MAX нет @username — id получается одноразовой командой 'python manage.py max_get_chat_id' после того как бот добавлен администратором в канал.", max_length=32, verbose_name='Chat ID')),
                ('link_text', models.CharField(default='Читать статью →', help_text='Показывается вместо длинного URL в тексте поста.', max_length=64, verbose_name='Текст ссылки на статью')),
            ],
            options={
                'verbose_name': 'Настройки MAX',
                'verbose_name_plural': 'Настройки MAX',
            },
        ),
        migrations.AddField(
            model_name='articlepage',
            name='max_posted_at',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='articlepage',
            name='max_posted_by',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
    ]
