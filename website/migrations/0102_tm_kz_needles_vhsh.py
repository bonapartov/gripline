"""13.10.2026: поле «Игла» у TM KZ — список вместо диапазона K46…K60: добавлены иглы настроек VHSH
(K3…K98, U2…U16), прежние K46…K60 остаются (старые сетапы не теряют значение).
"""
import re

from django.db import migrations

VHSH = ['K3', 'K8', 'K16', 'K21', 'K22', 'K23', 'K27', 'K28', 'K92', 'K93', 'K96', 'K97', 'K98',
        'U2', 'U3', 'U4', 'U7', 'U8', 'U12', 'U16']


def _key(n):
    m = re.match(r'([A-Z]+)(\d+)', n)
    return (m.group(1), int(m.group(2))) if m else (n, 0)


def seed(apps, schema_editor):
    Field = apps.get_model('website', 'AppEngineField')
    f = Field.objects.filter(engine__name='TM KZ', key='needle').first()
    if f is None:
        return
    if f.mode == 'list':
        current = [x.strip() for x in f.options_text.splitlines() if x.strip()]
    else:
        lo, hi, step = int(f.min_value), int(f.max_value), int(f.step or 1)
        current = [f'{f.value_prefix}{i}' for i in range(lo, hi + 1, step)]
    options = sorted(set(current) | set(VHSH), key=_key)
    f.mode = 'list'
    f.options_text = '\n'.join(options)
    f.value_prefix = ''
    f.min_value = f.max_value = f.step = None
    f.save()


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0101_app_vhsh_tm_kz_seed'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
