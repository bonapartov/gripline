# Порядок классов картинга во всех фильтрах/вкладках сайта — раньше везде
# сортировались по алфавиту (RaceClass.Meta не задавал ordering, вызывающий
# код добавлял .order_by('name')/sorted(key=lambda x: x.name) в ~15 местах).
# Явный порядок вместо алфавита — по просьбе пользователя, согласован явно
# (включая классы, которых не было в изначальном списке: "Супер-мини ГР-3"
# сразу после "Супер-мини" по аналогии с "Мини"/"Мини ГР-3"; "E-10 МИНИ"/
# "E-10 БАМБИНИ" — в конец, после 4Т, как отдельная категория электрокартов,
# БАМБИНИ раньше МИНИ по возрастанию возраста; "РМ" без уточнения = "RM
# Senior" — базовый взрослый класс линейки RM; порядок внутри 4Т — Дети →
# Юноши → Взрослые).
#
# Шаг кратен 10 — чтобы админ мог вставить новый класс между существующими
# через панель "Порядок сортировки" (RaceClass.panels), не перенумеровывая
# всё подряд.

from django.db import migrations

ORDER = [
    "Микро",
    "Мини",
    "Мини ГР-3",
    "Супер-мини",
    "Супер-мини ГР-3",
    "ОК J",
    "ОК",
    "KZ2",
    "KZ2 Masters",
    "RM Micro",
    "RM Mini",
    "RM Junior",
    "RM Senior",
    "RM DD2",
    "RM DD2 Masters",
    "4Т Дети",
    "4Т Юноши",
    "4Т Взрослые",
    "E-10 БАМБИНИ",
    "E-10 МИНИ",
]


def seed_sort_order(apps, schema_editor):
    RaceClass = apps.get_model("website", "RaceClass")
    for index, name in enumerate(ORDER):
        RaceClass.objects.filter(name=name).update(sort_order=(index + 1) * 10)


def noop_reverse(apps, schema_editor):
    # Обратная миграция намеренно не восстанавливает sort_order=0 — поле
    # само по себе остаётся (удаляется отдельной AddField-миграцией при
    # откате 0041), откатывать тут нечего.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0041_add_raceclass_sort_order'),
    ]

    operations = [
        migrations.RunPython(seed_sort_order, noop_reverse),
    ]
