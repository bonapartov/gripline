"""Стартовое наполнение справочников приложения GripLine SetupKart (ТЗ приложения §13.3).

Профили карбюраторов (Приложение A, данные со скриншотов SetupKart Pro) прикрепляются к существующим
двигателям сайта по семейству. Двигатели не создаются (у них публичные страницы) — их заводят в
«Техника → Двигатели». Уже настроенные двигатели (есть поля карбюратора) не трогаются.

  python manage.py setupkart_seed_profiles --dry-run          # что будет сделано
  python manage.py setupkart_seed_profiles                    # по названию: «Rotax …» → Rotax и т. д.
  python manage.py setupkart_seed_profiles --engine "Rotax FR 125" --family rotax
"""
import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from website.models import AppEngineField, AppEngineSparkPlug, AppParameter, Engine

SEED = Path(__file__).resolve().parents[2] / 'setupkart' / 'seed_engines.json'
FAMILIES = ('rotax', 'iame', 'vortex', 'tm', 'honda', 'briggs')

PARAMS = [
    dict(key='hub_width_mm', unit='мм', mode='list', options_text='40\n50\n55\n60\n65\n70\n75\n80', default_value='50'),
    dict(key='pinion_teeth', mode='list', options_text='11\n12\n13', default_value='12'),
    dict(key='sprocket_teeth', mode='range', min_value=66, max_value=85, step=1, default_value='75'),
    dict(key='spacer', mode='range', min_value=0, max_value=5, step=Decimal('0.5'), default_value='2.0',
         allow_custom=False),
]


def load_seed():
    data = json.loads(SEED.read_text(encoding='utf-8'))
    return {e['id']: e for e in data['engines']}


def field_kwargs(f):
    kw = dict(key=f['key'], unit=f.get('unit', ''), allow_custom=f.get('allow_custom', False),
              default_value=str(f.get('default', '')))
    if 'range' in f:
        r = f['range']
        kw.update(mode='range', min_value=Decimal(str(r['from'])), max_value=Decimal(str(r['to'])),
                  step=Decimal(str(r['step'])), prefix=r.get('prefix', ''))
    else:
        values = [o['value'] if isinstance(o, dict) else o for o in f.get('options', [])]
        kw.update(mode='list', options_text='\n'.join(values))
    return kw


class Command(BaseCommand):
    help = 'Прикрепляет стартовые профили карбюраторов к двигателям сайта и создаёт общие параметры приложения.'

    def add_arguments(self, parser):
        parser.add_argument('--engine', help='Название двигателя на сайте (точно)')
        parser.add_argument('--family', choices=FAMILIES, help='Профиль для --engine')
        parser.add_argument('--dry-run', action='store_true')

    @transaction.atomic
    def handle(self, *args, **opt):
        seed = load_seed()
        if opt['engine']:
            if not opt['family']:
                raise CommandError('С --engine нужен --family')
            engine = Engine.objects.filter(name=opt['engine']).first()
            if engine is None:
                raise CommandError(f'Двигатель «{opt["engine"]}» не найден')
            targets = [(engine, opt['family'])]
        else:
            targets = []
            for engine in Engine.objects.order_by('name'):
                fam = next((f for f in FAMILIES if engine.name.lower().startswith(f)), None)
                if fam:
                    targets.append((engine, fam))
                else:
                    self.stdout.write(f'  пропуск: «{engine.name}» — нет стартового профиля (заполните в админке)')

        for engine, fam in targets:
            if engine.app_fields.exists():
                self.stdout.write(f'  уже настроен: «{engine.name}» — не трогаю')
                continue
            profile = seed[fam]
            fields = [f for f in profile['carburetor_fields'] if f['key'] != 'spark_plug']
            plugs = next((f for f in profile['carburetor_fields'] if f['key'] == 'spark_plug'), None)
            self.stdout.write(f'  «{engine.name}» ← {profile["make"]}: {len(fields)} полей, '
                              f'{len(plugs["options"]) if plugs else 0} свечей')
            if opt['dry_run']:
                continue
            for i, f in enumerate(fields):
                AppEngineField.objects.create(engine=engine, sort_order=i, **field_kwargs(f))
            if plugs:
                for i, name in enumerate(plugs['options']):
                    AppEngineSparkPlug.objects.create(engine=engine, sort_order=i, name=name,
                                                      is_default=(name == plugs.get('default')))
            if not engine.app_family:
                Engine.objects.filter(pk=engine.pk).update(app_family=fam)

        for p in PARAMS:
            if AppParameter.objects.filter(key=p['key']).exists():
                continue
            self.stdout.write(f'  параметр: {p["key"]}')
            if not opt['dry_run']:
                AppParameter.objects.create(**p)

        if opt['dry_run']:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING('Пробный прогон — ничего не записано.'))
        else:
            self.stdout.write(self.style.SUCCESS('Готово. Отметьте «Показывать в приложении» у нужных двигателей и опубликуйте.'))
