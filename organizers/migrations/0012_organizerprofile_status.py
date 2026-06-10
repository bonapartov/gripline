from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizers', '0011_championship_is_demo'),
    ]

    operations = [
        migrations.AddField(
            model_name='organizerprofile',
            name='status',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('pending', 'Ожидает активации'),
                    ('active', 'Активен'),
                    ('rejected', 'Отклонён'),
                ],
                default='active',
                verbose_name='Статус',
            ),
        ),
    ]
