from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='applicationpayment',
            name='organizer_comment',
            field=models.TextField(blank=True, verbose_name='Комментарий организатора'),
        ),
        migrations.AlterField(
            model_name='applicationpayment',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Ожидает квитанции'),
                    ('uploaded', 'На проверке у организатора'),
                    ('verified', 'Оплата подтверждена'),
                    ('rejected', 'Квитанция отклонена'),
                    ('refunded', 'Возвращена'),
                ],
                default='pending', max_length=20, verbose_name='Статус',
            ),
        ),
    ]
