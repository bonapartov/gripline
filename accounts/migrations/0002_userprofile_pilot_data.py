from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='middle_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='Отчество'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='birth_date',
            field=models.DateField(blank=True, null=True, verbose_name='Дата рождения'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='citizenship',
            field=models.CharField(blank=True, default='Россия', max_length=100, verbose_name='Гражданство'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='phone',
            field=models.CharField(blank=True, max_length=30, verbose_name='Телефон'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='license_number',
            field=models.CharField(blank=True, max_length=100, verbose_name='Лицензия пилота'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='sport_rank',
            field=models.CharField(blank=True, max_length=100, verbose_name='Спортивное звание'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='parent_last_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='Фамилия родителя'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='parent_first_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='Имя родителя'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='parent_middle_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='Отчество родителя'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='parent_relation',
            field=models.CharField(blank=True, choices=[('mother', 'Мать'), ('father', 'Отец'), ('guardian', 'Опекун/попечитель')], max_length=20, verbose_name='Кем приходится'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='parent_phone',
            field=models.CharField(blank=True, max_length=30, verbose_name='Телефон родителя'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='parent_email',
            field=models.EmailField(blank=True, max_length=254, verbose_name='Email родителя'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='default_chassis_brand',
            field=models.CharField(blank=True, max_length=100, verbose_name='Марка шасси'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='default_engine',
            field=models.CharField(blank=True, max_length=100, verbose_name='Двигатель'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='default_transponder',
            field=models.CharField(blank=True, max_length=50, verbose_name='Номер транспондера AMB'),
        ),
    ]
