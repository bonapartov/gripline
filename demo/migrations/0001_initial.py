from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='DemoSlot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slot_type', models.CharField(choices=[('organizer', 'Организатор'), ('pilot', 'Пилот'), ('team', 'Команда')], max_length=20)),
                ('slot_number', models.IntegerField()),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='demo_slot', to='auth.user')),
                ('is_occupied', models.BooleanField(default=False)),
                ('occupied_until', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Демо-слот',
                'verbose_name_plural': 'Демо-слоты',
                'ordering': ['slot_type', 'slot_number'],
                'unique_together': {('slot_type', 'slot_number')},
            },
        ),
    ]
