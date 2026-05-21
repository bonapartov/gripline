from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_userprofile_pilot_data'),
    ]

    operations = [
        migrations.CreateModel(
            name='PilotDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Название документа')),
                ('file', models.FileField(upload_to='pilot_documents/', verbose_name='Файл')),
                ('expiry_date', models.DateField(blank=True, null=True, verbose_name='Срок действия')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True, verbose_name='Загружен')),
                ('profile', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='documents',
                    to='accounts.userprofile',
                    verbose_name='Профиль',
                )),
            ],
            options={
                'verbose_name': 'Документ пилота',
                'verbose_name_plural': 'Документы пилота',
                'ordering': ['name'],
            },
        ),
    ]
