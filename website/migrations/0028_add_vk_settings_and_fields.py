import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0027_rename_tag_to_social'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='VkSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('group_id', models.CharField(blank=True, help_text="Числовой ID сообщества VK (без минуса). Получается одноразовой командой 'python manage.py vk_get_group_id --screen-name gripline'.", max_length=32, verbose_name='Group ID')),
                ('link_text', models.CharField(default='Читать статью →', help_text='Показывается вместо длинного URL в тексте поста.', max_length=64, verbose_name='Текст ссылки на статью')),
            ],
            options={
                'verbose_name': 'Настройки VK',
                'verbose_name_plural': 'Настройки VK',
            },
        ),
        migrations.AddField(
            model_name='articlepage',
            name='vk_posted_at',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='articlepage',
            name='vk_posted_by',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
    ]
