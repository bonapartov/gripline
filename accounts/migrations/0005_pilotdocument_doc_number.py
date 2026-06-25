from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_yandex_social_auth'),
    ]

    operations = [
        migrations.AddField(
            model_name='pilotdocument',
            name='doc_number',
            field=models.CharField(blank=True, max_length=100, verbose_name='Номер документа'),
        ),
    ]
