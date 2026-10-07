from django.db import migrations


class Migration(migrations.Migration):
    """prefix → value_prefix: имя «prefix» перекрывало служебный атрибут формы и ломало разметку инлайнов."""

    dependencies = [
        ('website', '0056_setupkart_feedback_channel'),
    ]

    operations = [
        migrations.RenameField('appenginefield', 'prefix', 'value_prefix'),
        migrations.RenameField('appparameter', 'prefix', 'value_prefix'),
    ]
