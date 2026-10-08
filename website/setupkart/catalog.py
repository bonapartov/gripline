"""Сборка справочников приложения из админки, проверка и публикация версией (ТЗ приложения §13.3)."""
from django.db import transaction
from django.db.models import Count, Max

from website.models import (
    APP_ENGINE_FIELD_CHOICES, APP_PARAMETER_CHOICES, AppCatalogVersion, AppParameter, Chassis, Engine,
    TyreBrand,
)
from . import chassis_images
from .spec import spec_errors, to_profile_field

SCHEMA = 1
FIELD_LABELS = dict(APP_ENGINE_FIELD_CHOICES)
PARAM_LABELS = dict(APP_PARAMETER_CHOICES)


def _live(qs):
    """Только опубликованные на сайте записи (DraftStateMixin) с галочкой приложения."""
    return qs.filter(show_in_app=True, live=True)


def app_engines():
    return (_live(Engine.objects)
            .prefetch_related('app_fields', 'app_spark_plugs', 'app_race_classes')
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
        'carburetor_fields': fields,
    }


def app_tyre_brands():
    return _live(TyreBrand.objects).prefetch_related('app_compounds__image').order_by('name')


def _tyre_brand_payload(brand):
    return {
        'id': brand.pk,
        'name': brand.name,
        'compounds': [{'name': c.name.strip(), 'kind': c.kind, 'image': chassis_images.compound_image(c)}
                      for c in brand.app_compounds.all()],
    }


def build_payload():
    """Текущее состояние админки в формате, который получает приложение."""
    engines = list(app_engines())
    class_ids = {rc.pk for e in engines for rc in e.app_race_classes.all()}
    from website.models import RaceClass
    return {
        'schema': SCHEMA,
        'engines': [_engine_payload(e) for e in engines],
        'race_classes': [{'id': rc.pk, 'name': rc.name, 'sort_order': rc.sort_order}
                         for rc in RaceClass.objects.filter(pk__in=class_ids)],
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
