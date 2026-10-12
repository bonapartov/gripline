"""Поплавковый карбюратор по погоде (13.10.2026): справка для строк Rotax и модификации Vortex ROK из
«Jetting for Vortex ROK» 1.4.0 (JetLab; только числа, см. docs/carb_float_by_weather.md в приложении).
Классы ROK Cup (Mini ROK 110 кг, Junior ROK 145 кг, Senior ROK 160 кг) — «только для приложения».
"""
from decimal import Decimal as D

from django.db import migrations

ROTAX_INFO = "Пилотный жиклёр 60, диффузор 45, эмульсионная трубка 267, игла K57, поплавки 4,0 г."
GP_INFO = ("Игла K33 (K28 — если нужно сильно обеднить), холостой жиклёр 60, золотник 40, "
           "эмульсионная трубка DP 268, поплавки 2 × 4 г, высота поплавка 4 мм.")
MINI_INFO = "Холостой жиклёр 50, золотник 40, эмульсионная трубка DQ 266, поплавки 2 × 4 г."
GP_LADDER = "0.5:2.25; 1.75:2; 2.75:1.75; 3.75:1.5; 4.75:1.25; 1"
MINI_LADDER = "0.5:0.5; 1.75:0.75; 2.75:1; 3.75:1; 1.25"
ROK_SPARK = "10:NGK BR8EG; 25:NGK BR9EG; NGK BR10EG"

CLASSES = [('Mini ROK', 110, 'junior', 920), ('Junior ROK', 145, 'senior', 930), ('Senior ROK', 160, 'senior', 940)]

# (модификация, класс, база жиклёра, мини-модель)
ROK = [
    ('ROK GP', 'Senior ROK', '137.5', False),
    ('ROK GP Junior', 'Junior ROK', '130.368', False),
    ('ROK Mini', 'Mini ROK', '91.468', True),
    ('ROK Mini, рестриктор 16 мм', None, '91.047', True),
]


def seed(apps, schema_editor):
    Engine = apps.get_model('website', 'Engine')
    RaceClass = apps.get_model('website', 'RaceClass')
    Row = apps.get_model('website', 'AppEngineFloatCarbModel')
    Row.objects.filter(engine__name='Rotax FR 125', extra_info='').update(extra_info=ROTAX_INFO)
    engine = Engine.objects.filter(name='Vortex ROK').first()
    if engine is None or Row.objects.filter(engine=engine).exists():
        return
    classes = {}
    for name, weight, chassis, order in CLASSES:
        rc = RaceClass.objects.filter(name=name).first()
        if rc is None:
            rc = RaceClass.objects.create(name=name, app_only=True, min_weight_kg=D(weight), chassis_type=chassis,
                                          sort_order=order)
        classes[name] = rc
    for i, (name, cls, jet, mini) in enumerate(ROK):
        Row.objects.create(
            engine=engine, sort_order=i, name=name, race_class=classes.get(cls), is_default=(i == 0),
            jet_base=D(jet),
            jet_slope=D('0.3350888192653656' if mini else '0.4350888133049011'),
            jet_intercept=D('0.6117' if mini else '0.4917'),
            jet_rounding='step1' if mini else 'dellorto', fuel95_factor=D('1'),
            needle_slope=D('12.10694'), needle_offset=D('-12.14850'), air_screw_bonus=D('0'),
            air_screw_ladder=MINI_LADDER if mini else GP_LADDER,
            float_height_mm=D('4'), float_height_ref_mm=D('4'),
            float_factor_fixed=D('1.0440625') if mini else None, float_weight_g=D('4'),
            oil_pct=D('2'), water_temp_c=D('49'), gear_oil='75 мл ATF', spark_by_temp=ROK_SPARK,
            extra_info=MINI_INFO if mini else GP_INFO)


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0097_app_float_models_general'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
