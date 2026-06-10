from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_pilotdocument_doc_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='birth_date_public',
            field=models.BooleanField(
                default=False,
                help_text='Показывать дату рождения в публичной карточке пилота на сайте',
                verbose_name='Публиковать дату рождения',
            ),
        ),
    ]
