"""Винты High/Low по погоде для IAME X30 (13.10.2026): коэффициенты из «Jetting for IAME X30» 1.4.0
(только числа; см. docs/carb_screws_by_weather.md в репозитории приложения). Двигатель ищется по названию
«IAME X30»; если его нет или строки уже заведены — ничего не делает. Дальше правится в админке.
"""
from decimal import Decimal as D

from django.db import migrations

# (модификация, карбюратор, поправка модели, High смещение, Low наклон, Low смещение, открытие PSI, закрытие PSI,
#  выхлоп мм, поправка выхлопа на длинной прямой, вода °C)
ROWS = [
    ('X30 Junior, рестриктор 22', 'Tillotson HW-27', '0.9581', '0.0012', '1.0881', '-0.2542', '10.8', '8.5', None, '-10', '51.7'),
    ('X30 Junior, рестриктор 22', 'Tryton HB-27', '0.9581', '-0.3542', '1.0281', '-0.2442', '10.3', '8.8', None, '-10', '51.7'),
    ('X30 Junior, рестриктор 22,7', 'Tillotson HW-27', '0.9581', '0.0212', '1.0881', '-0.2442', '10.8', '8.5', None, '-10', '51.7'),
    ('X30 Junior, рестриктор 22,7', 'Tryton HB-27', '0.9581', '-0.3342', '1.0281', '-0.2342', '10.3', '8.8', None, '-10', '51.7'),
    ('X30 Junior, рестриктор 26', 'Tillotson HW-27', '0.9581', '0.1812', '1.0881', '-0.2542', '10.8', '8.5', '463', '-10', '51.7'),
    ('X30 Junior, рестриктор 26', 'Tryton HB-27', '0.9581', '-0.2442', '1.0281', '-0.2042', '10.3', '8.8', '470', '-10', '51.7'),
    ('X30 Junior, рестриктор 29', 'Tillotson HW-27', '0.9581', '0.2012', '1.0881', '-0.2542', '10.8', '8.5', '451', '-10', '51.7'),
    ('X30 Junior, рестриктор 29', 'Tryton HB-27', '0.9581', '-0.2242', '1.0281', '-0.1842', '10.3', '8.8', '458', '-10', '51.7'),
    ('X30 Junior, рестриктор 31', 'Tillotson HW-27', '0.9581', '0.2212', '1.0881', '-0.2542', '10.8', '8.5', '444.5', '-10', '51.7'),
    ('X30 Junior, рестриктор 31', 'Tryton HB-27', '0.9581', '-0.2042', '1.0281', '-0.1842', '10.3', '8.8', '451.5', '-10', '51.7'),
    ('X30 Senior (коллектор + flex)', 'Tillotson HW-27', '0.9581', '0.2412', '1.0881', '-0.2442', '10.8', '8.5', '438', '-6', '54.5'),
    ('X30 Senior (коллектор + flex)', 'Tryton HB-27', '0.9581', '-0.1942', '1.0281', '-0.1742', '10.3', '8.8', '445', '-10', '54.5'),
    ('X30 Senior (одна труба)', 'Tillotson HW-27', '0.9581', '0.1712', '1.0881', '-0.1742', '10.8', '8.5', None, '-10', '54.5'),
    ('X30 Senior (одна труба)', 'Tryton HB-27', '0.9581', '-0.2642', '1.0281', '-0.1342', '10.3', '8.8', None, '-10', '54.5'),
]


def seed(apps, schema_editor):
    Engine = apps.get_model('website', 'Engine')
    Screw = apps.get_model('website', 'AppEngineScrewModel')
    engine = Engine.objects.filter(name='IAME X30').first()
    if engine is None or Screw.objects.filter(engine=engine).exists():
        return
    for i, (model, carb, factor, ho, ls, lo, po, pc, exh, exh_long, water) in enumerate(ROWS):
        Screw.objects.create(
            engine=engine, sort_order=i, name=f'{model} · {carb}', is_default=(i == 10),
            model_factor=D(factor), high_slope=D('1.0881'), high_offset=D(ho), low_slope=D(ls), low_offset=D(lo),
            popoff_open_psi=D(po), popoff_close_psi=D(pc), exhaust_mm=D(exh) if exh else None,
            exhaust_long_straight_mm=D(exh_long), water_temp_c=D(water), egt_min_c=593, egt_max_c=635,
            plug_gap_mm=D('0.75'))


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0092_app_engine_screw_models'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
