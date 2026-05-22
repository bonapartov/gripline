from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizers', '0005_stage_registration_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='championship',
            name='is_published',
            field=models.BooleanField(default=True, verbose_name='Опубликован на сайте'),
        ),
        migrations.AddField(
            model_name='championship',
            name='color',
            field=models.CharField(default='#ffc107', max_length=7, verbose_name='Цвет в календаре'),
        ),
    ]
