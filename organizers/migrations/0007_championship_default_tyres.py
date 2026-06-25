from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizers', '0006_championship_published_color'),
        ('website', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='championship',
            name='default_tyre',
        ),
        migrations.AddField(
            model_name='championship',
            name='default_tyres',
            field=models.ManyToManyField(
                blank=True,
                help_text='Разрешённые шины для чемпионата',
                to='website.tyre',
            ),
        ),
    ]
