from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0002_payment_comment_status_labels'),
        ('organizers', '0009_championship_registration_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChampionshipDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Название документа')),
                ('description', models.TextField(blank=True, verbose_name='Пояснение')),
                ('required', models.BooleanField(default=True, verbose_name='Обязательный')),
                ('minors_only', models.BooleanField(default=False, verbose_name='Только для несовершеннолетних')),
                ('has_expiry_date', models.BooleanField(default=False, verbose_name='Есть срок действия')),
                ('order', models.PositiveIntegerField(default=0)),
                ('championship', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='championship_documents', to='organizers.championship')),
            ],
            options={'verbose_name': 'Документ чемпионата', 'verbose_name_plural': 'Документы чемпионата', 'ordering': ['order']},
        ),
        migrations.CreateModel(
            name='ChampionshipOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Название')),
                ('description', models.TextField(blank=True, verbose_name='Описание')),
                ('price', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Цена (₽)')),
                ('is_mandatory', models.BooleanField(default=False, verbose_name='Обязательная')),
                ('is_active', models.BooleanField(default=True, verbose_name='Доступна')),
                ('order', models.PositiveIntegerField(default=0)),
                ('championship', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='championship_options', to='organizers.championship')),
            ],
            options={'verbose_name': 'Опция чемпионата', 'verbose_name_plural': 'Опции чемпионата', 'ordering': ['order']},
        ),
    ]
