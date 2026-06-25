from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0008_analytics_settings_trend_window'),
    ]

    operations = [
        migrations.AddField(
            model_name='teammembership',
            name='race_class',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='website.raceclass',
                verbose_name='Класс',
            ),
        ),
    ]
