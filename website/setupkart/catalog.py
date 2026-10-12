"""Сборка справочников приложения из админки, проверка и публикация версией (ТЗ приложения §13.3)."""
from django.db import transaction
from django.db.models import Count, Max

from website.models import (
    APP_ENGINE_FIELD_CHOICES, APP_PARAMETER_CHOICES, AppCatalogVersion, AppParameter, Chassis, Engine,
    TyreBrand,
)
from . import chassis_images
from .spec import expand, spec_errors, to_profile_field

SCHEMA = 1
FIELD_LABELS = dict(APP_ENGINE_FIELD_CHOICES)
PARAM_LABELS = dict(APP_PARAMETER_CHOICES)


def _live(qs):
    """Только опубликованные на сайте записи (DraftStateMixin) с галочкой приложения."""
    return qs.filter(show_in_app=True, live=True)


def app_engines():
    return (_live(Engine.objects)
            .select_related('app_carburetor_image')
            .prefetch_related('app_fields', 'app_spark_plugs', 'app_race_classes', 'app_class_presets', 'app_jet_bases')
            .order_by('name'))


def _engine_payload(engine):
    fields = [to_profile_field(f, f.key, FIELD_LABELS.get(f.key, f.key)) for f in engine.app_fields.all()]
    plugs = [p.name for p in engine.app_spark_plugs.all()]
    if plugs:
        default = next((p.name for p in engine.app_spark_plugs.all() if p.is_default), plugs[0])
        fields.append({'key': 'spark_plug', 'label': 'Свеча', 'type': 'choice',
                       'options': plugs, 'default': default, 'allow_custom': True})
    return {
        'id': engine.pk,
        'name': engine.name,
        'family': engine.app_family or 'other',
        'race_class_ids': [rc.pk for rc in engine.app_race_classes.all()],
        'electric': engine.app_electric,
        'carburetor_fields': fields,
        'carburetor_image': chassis_images.carburetor_image(engine),
        # Рекомендации производителя по классу: {id класса: {поле: {value, from, to}}} (11.10.2026).
        'class_presets': _class_presets_payload(engine),
        # Пересчёт жиклёра под RAD сессии (формула Rotax MAX Jetting, 12.10.2026): базы по классам
        # {id класса: {base, legacy?}} при RAD base_rad; null — не пересчитывать.
        'jet_by_rad': _jet_by_rad_payload(engine),
    }


def _jet_by_rad_payload(engine):
    bases = {str(b.race_class_id): {'base': b.base, **({'legacy': b.base_legacy} if b.base_legacy else {})}
             for b in engine.app_jet_bases.all()}
    if engine.app_jet_base_rad is None or not bases:
        return None
    return {'base_rad': float(engine.app_jet_base_rad), 'step': engine.app_jet_step or 1, 'bases': bases}


def _class_presets_payload(engine):
    out = {}
    for p in engine.app_class_presets.all():
        item = {k: v.strip() for k, v in (('value', p.value), ('from', p.range_from), ('to', p.range_to)) if v.strip()}
        if item:
            out.setdefault(str(p.race_class_id), {})[p.key] = item
    return out


def app_tyre_brands():
    return _live(TyreBrand.objects).prefetch_related('app_compounds__image').order_by('name')


def _tyre_brand_payload(brand):
    return {
        'id': brand.pk,
        'name': brand.name,
        'compounds': [{'name': c.name.strip(), 'kind': c.kind, 'image': chassis_images.compound_image(c)}
                      for c in brand.app_compounds.all()],
    }


def _balance_payload():
    """Развесовка в приложении: пороги цветовых зон и тексты диагностики из «Развесовки» (те же, что на
    /balance/). Формулы — в приложении (третья копия: Python/JS/Dart, сверяются общими контрольными
    примерами website/tests/fixtures/balance_vectors.json)."""
    from django.conf import settings
    from website.models import BalanceDiagnosticRule, BalanceThreshold
    base = settings.BASE_URL.rstrip('/')

    def zone(t):
        return {'green_min': float(t.green_min), 'green_max': float(t.green_max),
                'yellow_min': float(t.yellow_min), 'yellow_max': float(t.yellow_max)}

    by_class = {}
    for t in BalanceThreshold.objects.filter(race_class__isnull=False).order_by('race_class_id', 'metric'):
        by_class.setdefault(str(t.race_class_id), {})[t.metric] = zone(t)
    return {
        'thresholds': {t.metric: zone(t) for t in BalanceThreshold.objects.filter(race_class__isnull=True)},
        # Эталон класса: {id класса: {метрика: зоны}} — заменяет общий порог той же метрики (11.10.2026).
        'class_thresholds': by_class,
        'rules': {r.condition: {'text': r.text, 'article_url': f"{base}{r.article.url}" if r.article_id else ''}
                  for r in BalanceDiagnosticRule.objects.select_related('article')},
    }


def build_payload():
    """Текущее состояние админки в формате, который получает приложение."""
    engines = list(app_engines())
    class_ids = {rc.pk for e in engines for rc in e.app_race_classes.all()}
    from website.models import RaceClass
    return {
        'schema': SCHEMA,
        'engines': [_engine_payload(e) for e in engines],
        'race_classes': [{'id': rc.pk, 'name': rc.name, 'sort_order': rc.sort_order,
                          'min_weight_kg': float(rc.min_weight_kg) if rc.min_weight_kg else None}
                         for rc in RaceClass.objects.filter(pk__in=class_ids)],
        'balance': _balance_payload(),
        # Популярные марки (больше результатов на сайте) — первыми; синонимы — для «Другое…».
        'chassis': [{'id': c.pk, 'name': c.name, 'aliases': c.alias_list()}
                    for c in _live(Chassis.objects).annotate(n=Count('race_results')).order_by('-n', 'name')],
        'tyre_brands': [_tyre_brand_payload(t) for t in app_tyre_brands()],
        'chassis_images': chassis_images.payload(),
        'help_images': chassis_images.help_images_payload(),
        'params': {p.key: to_profile_field(p, p.key, PARAM_LABELS.get(p.key, p.key))
                   for p in AppParameter.objects.all()},
    }


def validation_errors():
    """Список понятных сообщений; публикация возможна только при пустом списке."""
    errors = []
    for e in app_engines():
        fields = list(e.app_fields.all())
        if e.app_electric:
            # Электромотор: карбюратора и свечи нет — лишние поля в приложении всё равно не показались бы.
            if fields or e.app_spark_plugs.exists():
                errors.append(f'«{e.name}»: у электромотора не должно быть полей карбюратора и свечей '
                              f'(вкладка «Приложение»).')
            continue
        if not fields:
            errors.append(f'«{e.name}»: нет ни одного поля карбюратора (вкладка «Приложение» в карточке двигателя).')
        seen = set()
        for f in fields:
            if f.key in seen:
                errors.append(f'«{e.name}»: поле «{f.get_key_display()}» добавлено дважды.')
            seen.add(f.key)
            for msg in spec_errors(f).values():
                errors.append(f'«{e.name}» → «{f.get_key_display()}»: {msg}')
        if sum(1 for p in e.app_spark_plugs.all() if p.is_default) > 1:
            errors.append(f'«{e.name}»: свеч «по умолчанию» больше одной.')
        by_key = {f.key: f for f in fields}
        if e.app_jet_base_rad is not None and not (50 <= e.app_jet_base_rad <= 130):
            errors.append(f'«{e.name}»: RAD рекомендаций жиклёра {e.app_jet_base_rad} — вне 50–130 %.')
        jet_bases = list(e.app_jet_bases.all())
        if e.app_jet_base_rad is not None and 'main_jet' not in by_key:
            errors.append(f'«{e.name}»: задан RAD для жиклёра, но поля «Главный жиклёр» нет среди полей карбюратора.')
        if e.app_jet_base_rad is not None and not jet_bases:
            errors.append(f'«{e.name}»: задан RAD базы жиклёра, но нет ни одной «Базы жиклёра по классу».')
        if jet_bases and e.app_jet_base_rad is None:
            errors.append(f'«{e.name}»: базы жиклёра по классам заданы, но не задан «RAD базы жиклёра».')
        class_ids = {rc.pk for rc in e.app_race_classes.all()}
        for b in jet_bases:
            if b.race_class_id not in class_ids:
                errors.append(f'«{e.name}» → база жиклёра «{b.race_class}»: класс не отмечен в «Классах в приложении».')
        for p in e.app_class_presets.all():
            where = f'«{e.name}» → рекомендация «{p.race_class}» · «{p.get_key_display()}»'
            if p.race_class_id not in class_ids:
                errors.append(f'{where}: класс не отмечен у двигателя.')
            field = by_key.get(p.key)
            if field is None:
                errors.append(f'{where}: такого поля нет среди полей карбюратора.')
            elif p.value.strip() and p.value.strip() not in expand(field):
                errors.append(f'{where}: значения «{p.value.strip()}» нет в списке поля '
                              f'(проверьте шаг и число знаков, например 1.75).')
            if not (p.value.strip() or p.range_from.strip() or p.range_to.strip()):
                errors.append(f'{where}: укажите значение или диапазон.')
    for p in AppParameter.objects.all():
        for msg in spec_errors(p).values():
            errors.append(f'Параметр «{p.get_key_display()}»: {msg}')
    for t in app_tyre_brands():
        seen = set()
        for c in t.app_compounds.all():
            name = c.name.strip().lower()
            if not name:
                errors.append(f'Шины «{t.name}»: у состава нет названия.')
            elif name in seen:
                errors.append(f'Шины «{t.name}»: состав «{c.name.strip()}» добавлен дважды.')
            seen.add(name)
    errors.extend(chassis_images.validation_errors())
    return errors


def latest_version():
    return AppCatalogVersion.objects.order_by('-version').first()


class PublishError(Exception):
    def __init__(self, errors):
        super().__init__('; '.join(errors))
        self.errors = errors


@transaction.atomic
def publish(user=None, note=''):
    errors = validation_errors()
    if errors:
        raise PublishError(errors)
    payload = build_payload()
    number = (AppCatalogVersion.objects.select_for_update().aggregate(m=Max('version'))['m'] or 0) + 1
    payload['version'] = number
    return AppCatalogVersion.objects.create(version=number, published_by=user, note=note, payload=payload)


def has_unpublished_changes():
    last = latest_version()
    if last is None:
        return True
    current = build_payload()
    current['version'] = last.version
    return current != last.payload
