from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0001_initial'),
        ('website', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TeamInvitation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[('pending', 'Ожидает ответа'), ('accepted', 'Принято'), ('declined', 'Отклонено')],
                    default='pending', max_length=20, verbose_name='Статус'
                )),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Дата приглашения')),
                ('responded_at', models.DateTimeField(blank=True, null=True, verbose_name='Дата ответа')),
                ('driver', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='team_invitations',
                    to='website.driver',
                    verbose_name='Пилот'
                )),
                ('invited_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='sent_invitations',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Пригласил'
                )),
                ('race_class', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='website.raceclass',
                    verbose_name='Класс'
                )),
                ('team', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='invitations',
                    to='website.team',
                    verbose_name='Команда'
                )),
            ],
            options={
                'verbose_name': 'Приглашение в команду',
                'verbose_name_plural': 'Приглашения в команду',
                'unique_together': {('driver', 'team')},
            },
        ),
    ]
