# Данные текстов диагностики — переносим формулировки прямо из ТЗ (раздел
# 7.1-7.2), не оставляем текст пустым. Ссылки на статьи Матчасти (article)
# сознательно НЕ проставляются здесь — какая статья куда ведёт, открытый
# вопрос ТЗ №10, редактируется через админку («Развесовка»), когда решится.

from django.db import migrations

RULES = [
    (
        "front_high",
        "Перегружен перед — склонность к недостаточной поворачиваемости "
        "(understeer) во всех поворотах одинаково.",
    ),
    (
        "front_low",
        "Перегружен зад — склонность к избыточной поворачиваемости "
        "(oversteer) во всех поворотах одинаково.",
    ),
    (
        "cross_diagonal",
        "Карт будет вести себя по-разному в левых и правых поворотах — "
        "проблема в диагонали (cross weight), а не в развесовке перед/зад.",
    ),
    (
        "cross_mechanical",
        "Проверьте механику: погнутые элементы рамы, крепление балласта, "
        "положение сиденья.",
    ),
    (
        "lr_asymmetry",
        "Асимметрия по бортам — карт нагружен неравномерно слева и справа.",
    ),
    (
        "wet_weather",
        "В дождь сместите развесовку на +1–2% на перед относительно сухой базы.",
    ),
    (
        "under_min_weight",
        "Недобор до минималки класса: {shortfall_kg} кг.",
    ),
    (
        "why_43_57_target",
        "У карта, в отличие от машины, цель не 50/50, а 43% перед / 57% зад. "
        "Жёсткая задняя ось без дифференциала требует отрыва внутреннего "
        "заднего колеса в повороте — а для этого нужна достаточная загрузка "
        "переда.",
    ),
]


def seed_rules(apps, schema_editor):
    BalanceDiagnosticRule = apps.get_model("website", "BalanceDiagnosticRule")
    for condition, text in RULES:
        BalanceDiagnosticRule.objects.get_or_create(condition=condition, defaults={"text": text})


def remove_rules(apps, schema_editor):
    BalanceDiagnosticRule = apps.get_model("website", "BalanceDiagnosticRule")
    BalanceDiagnosticRule.objects.filter(condition__in=[c for c, _ in RULES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0039_balancediagnosticrule'),
    ]

    operations = [
        migrations.RunPython(seed_rules, remove_rules),
    ]
