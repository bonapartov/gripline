"""Dell'Orto VHSH 30 по погоде для TM KZ (13.10.2026): модели двигателя и 12 базовых настроек из
«Jetting TM KZ KZ1 KZ2» 1.4.0 (JetLab; только числа, см. docs/carb_vhsh_by_weather.md в приложении).
"""
from decimal import Decimal as D

from django.db import migrations

RACING = "Свеча NGK Racing по температуре: R7282-9 (ниже −5 °C), R7282-10 (ниже 5), R7282-105 (ниже 18), R7282-11."
VARIANTS = [('K9', '0.9925'), ('K9B', '0.9975'), ('K9C', '0.9975'), ('KZ10', '1.0025'), ('KZ10B', '1.0075'),
            ('KZ10C', '1.0125'), ('KZ R1', '1.0125')]

# (жиклёр A, B; иглы; номер иглы; позиций клипсы; клипса A, B; трубка A, B; эмульсор тип, A, B;
#  холостой жиклёр A, B, минимум; воздушный винт; золотник)
SETUPS = [
    ('78.343', '76.3', 'K21, K28, K27', 2, 5, '9.328', '-9.1103', '16.486', '249.72', 'B', '35.616', '7', '0', '60', None, '1.5', 50),
    ('78.643', '78.3', 'K21, K98, K97', 2, 5, '9.328', '-8.6103', '16.486', '249.72', 'B', '35.616', '8', '0', '60', None, '1.5', 50),
    ('78.435', '77.928', 'K21, K22, K23', 2, 4, '9.328', '-8.6103', '16.486', '249.72', 'B', '35.616', '8', '0', '60', None, '1.5', 50),
    ('77.4', '76.9', 'K22, K23, K27', 2, 4, '9.328', '-8.9103', '16.486', '248.72', 'B', '35.616', '7', '0', '60', None, '1.5', 50),
    ('60.943', '70.285', 'K8, K3', 1, 3, '9.028', '-8.4103', '14.536', '249.9', 'CD', '0', '1', '28', '28', None, '1.75', 50),
    ('57.943', '70.785', 'K8, K3', 2, 3, '9.028', '-7.9103', '14.536', '248.9', 'B', '0', '70', '28', '28', None, '1.5', 50),
    ('56.036', '76.287', 'K92, K93', 2, 4, '12.536', '-12.504', '7.536', '256.9', 'CD', '0', '1', '27.5', '29', '50', '1.75', 50),
    ('76.931', '73.231', 'K16, K96', 2, 4, '8.428', '-7.9103', '22.452', '240.08', 'B', '36.616', '8', '0', '60', None, '1.75', 50),
    ('67.943', '61.785', 'U16, U7, U2', 2, 4, '8.428', '-8.1103', '14.536', '248.1', 'B', '35.616', '0', '0', '60', None, '1.75', 50),
    ('68.231', '62.831', 'U7, U2, U8', 2, 4, '8.428', '-8.1103', '14.536', '248.1', 'CD', '0', '1', '27.5', '28', None, '2', 55),
    ('62.943', '64.785', 'U12, U3', 1, 4, '8.928', '-8.7103', '16.486', '245.72', 'B', '0', '100', '24.5', '40', None, '2', 55),
    ('60.943', '67.785', 'U12, U3, U4', 2, 4, '8.428', '-8.3103', '16.486', '245.72', 'CD', '0', '1', '27.5', '29', None, '2', 55),
]


def seed(apps, schema_editor):
    Engine = apps.get_model('website', 'Engine')
    Variant = apps.get_model('website', 'AppEngineVhshVariant')
    Setup = apps.get_model('website', 'AppEngineVhshSetup')
    engine = Engine.objects.filter(name='TM KZ').first()
    if engine is None or Variant.objects.filter(engine=engine).exists():
        return
    for i, (name, factor) in enumerate(VARIANTS):
        Variant.objects.create(engine=engine, sort_order=i, name=name, engine_factor=D(factor),
                               is_default=(name == 'KZ R1'), extra_info=RACING)
    for i, row in enumerate(SETUPS):
        (ja, jb, needles, idx, clips, ca, cb, ea, eb, it, ia, ib, ja2, jb2, jmin, screw, slide) = row
        Setup.objects.create(
            engine=engine, sort_order=i, name=f'Настройка {i + 1}', jet_a=D(ja), jet_b=D(jb), needles=needles,
            needle_index=idx, needle_clips=clips, clip_a=D(ca), clip_b=D(cb), emulsion_a=D(ea), emulsion_b=D(eb),
            idle_emulsifier_type=it, idle_emulsifier_a=D(ia), idle_emulsifier_b=D(ib), idle_jet_a=D(ja2),
            idle_jet_b=D(jb2), idle_jet_min=D(jmin) if jmin else None, air_screw_turns=D(screw), throttle_valve=slide)


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0100_app_vhsh_carb'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
