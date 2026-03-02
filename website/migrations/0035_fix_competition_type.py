from django.db import migrations, models
import json

def convert_competition_type(apps, schema_editor):
    ChampionshipPage = apps.get_model('website', 'Championshippage')
    for page in ChampionshipPage.objects.all():
        old_value = page.competition_type

        # Если это строка-код (cup, championship, competition)
        if isinstance(old_value, str) and old_value in ['cup', 'championship', 'competition']:
            page.competition_type = json.dumps([old_value])
        # Если это None или пусто
        elif not old_value:
            page.competition_type = '[]'
        # Если это уже JSON-строка
        else:
            try:
                # Проверяем, валидный ли это JSON
                json.loads(old_value)
                page.competition_type = old_value
            except:
                # Если невалидный — оборачиваем в список
                page.competition_type = json.dumps([old_value])

        page.save()

class Migration(migrations.Migration):

    dependencies = [
        ('website', '0034_raceresult_penalty'),
    ]

    operations = [
        migrations.RunPython(convert_competition_type),
        migrations.AlterField(
            model_name='championshippage',
            name='competition_type',
            field=models.JSONField(default=list, blank=True),
        ),
    ]
