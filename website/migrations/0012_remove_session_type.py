from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0011_techarticleindexpage_alter_articlepage_body'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE website_raceclassresultgroup DROP COLUMN IF EXISTS session_type;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
