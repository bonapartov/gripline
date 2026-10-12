"""Поплавковый карбюратор по погоде для Rotax FR 125 (13.10.2026): коэффициенты из «Jetting Rotax Max EVO» 1.3.0
(JetLab; только числа, см. docs/carb_float_by_weather.md в репозитории приложения). Двигатель — по названию
«Rotax FR 125», классы — по названию; если строк уже есть — ничего не делает. Дальше правится в админке.
"""
from decimal import Decimal as D

from django.db import migrations

NEW, OLD = '21.1069434', '20.8669434'
# (модификация, класс по умолчанию, жиклёр новый/старый цилиндр, добавка наклона иглы, смещение иглы,
#  добавка воздушного винта, высота поплавка, вода °C, зазор свечи, свеча, масло в редукторе)
MODELS = [
    ('Micro MAX EVO (рестриктор RTX267536, 2020)', 'RM Micro', '108.01', '106.51', '0.28274811', '-21.99016797', '0.5', '2.5', '80', '1.15', 'NGK GR8DI-8', '60 мл ATF'),
    ('Micro MAX EVO (втулка RTX251731)', None, '106.4', '105.1', '0.28274811', '-21.99016797', '0.5', '2.5', '80', '1.1', 'NGK GR8DI-8', '60 мл ATF'),
    ('Micro MAX EVO (без рестриктора)', None, '119.0', '117.5', '0.2157481163740158', '-21.91016797956314', '0.5', '2.5', '80', '1.1', 'NGK GR8DI-8', '60 мл ATF'),
    ('Mini MAX EVO (2020)', 'RM Mini', '110.03', '109.01', '0.21574811', '-21.91016797', '0.5', '3.5', '65', '1.15', 'NGK GR8DI-8', '60 мл ATF'),
    ('Mini MAX EVO (до 2020)', None, '119.902', '118.3001', '0.21574811', '-21.91016797', '0.5', '3.5', '55', '1.0', 'NGK GR8DI-8', '60 мл ATF'),
    ('Junior MAX EVO', 'RM Junior', '121.072', '118.9138', '0.16385904', '-21.83381262', '0', '3.5', '55', '0.7', 'NGK GR9DI-8', '60 мл ATF'),
    ('Senior MAX EVO', 'RM Senior', '123.5', '120.9011', '0', '-21.6484959', '0', '3.5', '55', '0.7', 'NGK GR9DI-8', '60 мл ATF'),
    ('DD2 EVO', 'RM DD2', '131.32', '130.9', '0.14572594', '-21.79064192', '0', '3.5', '55', '0.7', 'NGK GR9DI-8', '125 мл ATF'),
]


def seed(apps, schema_editor):
    Engine = apps.get_model('website', 'Engine')
    RaceClass = apps.get_model('website', 'RaceClass')
    Row = apps.get_model('website', 'AppEngineFloatCarbModel')
    engine = Engine.objects.filter(name='Rotax FR 125').first()
    if engine is None or Row.objects.filter(engine=engine).exists():
        return
    order = 0
    for name, cls, jet_new, jet_old, slope_add, offset, bonus, fh, water, gap, plug, oil in MODELS:
        # Senior и DD2: «новый» цилиндр — с 2018 года, остальные — с 2017 (как в исходном расчёте).
        since = '2018' if name.startswith(('Senior', 'DD2')) else '2017'
        rc = RaceClass.objects.filter(name=cls).first() if cls else None
        for suffix, jet, base, klass in ((f'цилиндр {since}+', jet_new, NEW, rc), (f'цилиндр до {since}', jet_old, OLD, None)):
            Row.objects.create(
                engine=engine, sort_order=order, name=f'{name}, {suffix}', race_class=klass,
                is_default=(name.startswith('Senior') and klass is not None),
                jet_base=D(jet), needle_slope=D(base) + D(slope_add), needle_offset=D(offset),
                air_screw_bonus=D(bonus), float_height_mm=D(fh), oil_pct=D('2'), water_temp_c=D(water),
                plug_gap_mm=D(gap), spark_plug=plug, gear_oil=oil)
            order += 1
    dd2_masters = RaceClass.objects.filter(name='RM DD2 Masters').first()
    if dd2_masters:
        base = Row.objects.filter(engine=engine, name__startswith='DD2 EVO, цилиндр 2018+').first()
        if base:
            base.pk = None
            base.name = 'DD2 EVO Masters, цилиндр 2018+'
            base.race_class = dd2_masters
            base.sort_order = order
            base.save()


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0095_app_engine_float_models'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
