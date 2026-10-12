"""Справочники приложения GripLine SetupKart: админка, публикация, API (ТЗ приложения §13)."""
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.core.management import call_command

from website.models import (
    AppCatalogVersion, AppEngineField, AppEngineSparkPlug, AppParameter, AppSuggestion, Chassis, Engine, RaceClass,
    Track, TyreBrand,
)
from website.setupkart import catalog
from website.setupkart.spec import expand, spec_errors


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def make_engine(name='Rotax FR 125', show=True, **kw):
    e = Engine(name=name, live=True, show_in_app=show, **kw)
    e.save()
    return e


def rotax_seeded():
    e = make_engine()
    call_command('setupkart_seed_profiles', verbosity=0)
    e.refresh_from_db()
    return e


# ---------- значения поля ----------

def spec(**kw):
    base = dict(mode='range', min_value=None, max_value=None, step=None, value_prefix='', options_text='',
                default_value='', allow_custom=True)
    base.update(kw)
    return AppParameter(key='hub_width_mm', **base)


def test_range_expands_with_step_precision():
    s = spec(min_value=Decimal('0.25'), max_value=Decimal('6'), step=Decimal('0.25'), default_value='1.50')
    values = expand(s)
    assert values[0] == '0.25' and values[-1] == '6.00' and len(values) == 24
    assert spec_errors(s) == {}


def test_range_with_prefix():
    s = spec(min_value=46, max_value=60, step=1, value_prefix='K', default_value='K50')
    assert expand(s)[0] == 'K46' and expand(s)[-1] == 'K60'
    assert spec_errors(s) == {}


@pytest.mark.parametrize('kw, field', [
    (dict(min_value=1, max_value=10, step=0), 'step'),
    (dict(min_value=10, max_value=1, step=1), 'max_value'),
    (dict(min_value=0, max_value=1, step=Decimal('0.3')), 'max_value'),
    (dict(min_value=105, max_value=135, step=1, default_value='150'), 'default_value'),
    (dict(mode='list', options_text='  \n'), 'options_text'),
    (dict(min_value=0, max_value=10000, step=Decimal('0.01')), 'step'),
])
def test_spec_errors(kw, field):
    assert field in spec_errors(spec(**kw))


# ---------- стартовое заполнение ----------

@pytest.mark.django_db
def test_seed_attaches_rotax_profile_and_skips_engines_without_data():
    rotax = make_engine('Rotax FR 125', show=False)
    lifan = make_engine('Lifan 168f', show=False)
    call_command('setupkart_seed_profiles', verbosity=0)
    rotax.refresh_from_db()
    keys = list(rotax.app_fields.values_list('key', flat=True))
    assert keys == ['main_jet', 'idle_turns', 'air_screw_turns', 'needle_position', 'plug_gap_mm']
    assert rotax.app_family == 'rotax'
    assert list(rotax.app_spark_plugs.values_list('name', 'is_default')) == [('GR8DI-8', False), ('GR9DI-8', True)]
    assert not lifan.app_fields.exists()
    assert AppParameter.objects.count() == 4
    for f in rotax.app_fields.all():
        assert spec_errors(f) == {}, f.key
    for p in AppParameter.objects.all():
        assert spec_errors(p) == {}, p.key


@pytest.mark.django_db
def test_seed_is_idempotent_and_dry_run_writes_nothing():
    make_engine('Rotax FR 125')
    call_command('setupkart_seed_profiles', '--dry-run', verbosity=0)
    assert AppEngineField.objects.count() == 0 and AppParameter.objects.count() == 0
    call_command('setupkart_seed_profiles', verbosity=0)
    call_command('setupkart_seed_profiles', verbosity=0)
    assert AppEngineField.objects.count() == 5 and AppEngineSparkPlug.objects.count() == 2


@pytest.mark.django_db
def test_seed_explicit_engine_and_family():
    e = make_engine('X30 Junior')
    call_command('setupkart_seed_profiles', '--engine', 'X30 Junior', '--family', 'iame', verbosity=0)
    assert set(e.app_fields.values_list('key', flat=True)) == {'needle_high', 'needle_low', 'plug_gap_mm'}


# ---------- сборка и публикация ----------

@pytest.mark.django_db
def test_payload_contains_only_flagged_and_live_records():
    e = rotax_seeded()
    rc = RaceClass.objects.create(name='Rotax Junior', sort_order=10, min_weight_kg=145)
    e.app_race_classes.add(rc)
    e.save()  # ParentalManyToMany пишется только при save()
    make_engine('Hidden', show=False)
    Chassis.objects.create(name='Tony Kart', live=True, show_in_app=True)
    Chassis.objects.create(name='Not in app', live=True)
    TyreBrand.objects.create(name='Vega', live=True, show_in_app=True)
    TyreBrand.objects.create(name='Draft brand', live=False, show_in_app=True)

    p = catalog.build_payload()
    assert [x['name'] for x in p['engines']] == ['Rotax FR 125']
    eng = p['engines'][0]
    assert eng['family'] == 'rotax' and eng['race_class_ids'] == [rc.pk]
    by_key = {f['key']: f for f in eng['carburetor_fields']}
    assert by_key['main_jet']['range'] == {'from': 105.0, 'to': 135.0, 'step': 1.0, 'decimals': 0, 'prefix': ''}
    assert by_key['needle_position']['type'] == 'radio'
    assert by_key['needle_position']['options'][0] == {'value': '1', 'label': '1 — бедная'}
    assert by_key['spark_plug'] == {'key': 'spark_plug', 'label': 'Свеча', 'type': 'choice',
                                    'options': ['GR8DI-8', 'GR9DI-8'], 'default': 'GR9DI-8', 'allow_custom': True}
    assert [c['name'] for c in p['chassis']] == ['Tony Kart']
    assert [t['name'] for t in p['tyre_brands']] == ['Vega']
    assert p['race_classes'] == [{'id': rc.pk, 'name': 'Rotax Junior', 'sort_order': 10, 'min_weight_kg': 145.0}]
    assert p['balance'] == {'thresholds': {}, 'class_thresholds': {}, 'rules': {}}, 'пустая «Развесовка» — пустые пороги и правила'
    from website.models import BalanceDiagnosticRule, BalanceThreshold
    BalanceThreshold.objects.create(metric='front_rear', green_min=42.5, green_max=43.5, yellow_min=42, yellow_max=44)
    BalanceDiagnosticRule.objects.create(condition='front_high', text='Перегружен перед')
    balance = catalog.build_payload()['balance']
    assert balance['thresholds']['front_rear'] == {'green_min': 42.5, 'green_max': 43.5, 'yellow_min': 42.0,
                                                   'yellow_max': 44.0}
    assert balance['rules']['front_high'] == {'text': 'Перегружен перед', 'article_url': ''}
    assert set(p['params']) >= {'hub_width_mm', 'sprocket_teeth', 'spacer'}


@pytest.mark.django_db
def test_cannot_publish_engine_without_fields():
    make_engine('Lifan 168f')
    errors = catalog.validation_errors()
    assert any('Lifan 168f' in e and 'нет ни одного поля' in e for e in errors)
    with pytest.raises(catalog.PublishError):
        catalog.publish()
    assert AppCatalogVersion.objects.count() == 0


@pytest.mark.django_db
def test_electric_engine_published_without_carburetor():
    """Электромотор (Rotax E10): публикуется без полей карбюратора, в справочнике — признак electric."""
    from website.models import AppEngineSparkPlug, RaceClass
    e10 = make_engine('Rotax E10', app_electric=True)
    rc = RaceClass.objects.create(name='E-10 МИНИ')
    e10.app_race_classes.add(rc)
    e10.save()
    assert catalog.validation_errors() == []
    payload = catalog.build_payload()
    eng = next(x for x in payload['engines'] if x['name'] == 'Rotax E10')
    assert (eng['electric'], eng['carburetor_fields']) == (True, [])
    assert [c['name'] for c in payload['race_classes']] == ['E-10 МИНИ']
    catalog.publish()
    AppEngineSparkPlug.objects.create(engine=e10, name='NGK BR9EG')
    assert any('Rotax E10' in x and 'электромотора' in x for x in catalog.validation_errors())


@pytest.mark.django_db
def test_cannot_publish_invalid_field():
    e = rotax_seeded()
    AppEngineField.objects.filter(engine=e, key='main_jet').update(default_value='999')
    assert any('Главный жиклёр' in m for m in catalog.validation_errors())


@pytest.mark.django_db
def test_publish_increments_version_and_tracks_changes():
    rotax_seeded()
    assert catalog.has_unpublished_changes()
    v1 = catalog.publish(note='первая')
    assert v1.version == 1 and v1.payload['version'] == 1
    assert not catalog.has_unpublished_changes()
    AppEngineSparkPlug.objects.create(engine=Engine.objects.get(), name='GR10DI-8')
    assert catalog.has_unpublished_changes()
    assert catalog.publish().version == 2


# ---------- API ----------

@pytest.mark.django_db
def test_catalog_api(client):
    assert client.get('/api/setupkart/catalog/').status_code == 404
    rotax_seeded()
    catalog.publish()
    r = client.get('/api/setupkart/catalog/')
    assert r.status_code == 200 and r.json()['version'] == 1
    assert r.json()['engines'][0]['name'] == 'Rotax FR 125'
    assert client.get('/api/setupkart/catalog/?since=1').json() == {'version': 1, 'unchanged': True}
    # неопубликованное не уходит
    AppEngineSparkPlug.objects.create(engine=Engine.objects.get(), name='GR10DI-8')
    plugs = next(f for f in client.get('/api/setupkart/catalog/').json()['engines'][0]['carburetor_fields']
                 if f['key'] == 'spark_plug')
    assert 'GR10DI-8' not in plugs['options']


@pytest.mark.django_db
def test_tracks_api_only_flagged_with_coordinates(client):
    Track.objects.create(name='Мячково', live=True, show_in_app=True, latitude=55.56, longitude=38.0)
    Track.objects.create(name='Без координат', live=True, show_in_app=True)
    Track.objects.create(name='Только сайт', live=True, latitude=1, longitude=2)
    data = client.get('/api/setupkart/tracks/').json()
    assert [t['name'] for t in data['tracks']] == ['Мячково']
    assert client.get(f'/api/setupkart/tracks/?since={data["version"]}').json()['unchanged'] is True


@pytest.mark.django_db
def test_suggestions_api(client):
    e = rotax_seeded()
    post = lambda body: client.post('/api/setupkart/suggestions/', body, content_type='application/json')
    assert post({'field_key': 'spark_plug', 'value': ' NGK  BR9ES ', 'engine_id': e.pk, 'client_id': 'a'}).status_code == 201
    assert post({'field_key': 'spark_plug', 'value': 'NGK BR9ES', 'engine_id': e.pk, 'client_id': 'b'}).status_code == 200
    s = AppSuggestion.objects.get()
    assert s.value == 'NGK BR9ES' and s.count == 2 and s.engine == e
    assert post({'field_key': 'password', 'value': 'x'}).status_code == 400
    assert post({'field_key': 'spark_plug', 'value': 'x' * 61}).status_code == 400
    assert post({'field_key': 'spark_plug', 'value': 'x', 'engine_id': 999999}).status_code == 400
    assert client.post('/api/setupkart/suggestions/', 'not json', content_type='application/json').status_code == 400


@pytest.mark.django_db
def test_suggestions_rate_limited_per_client(client):
    post = lambda: client.post('/api/setupkart/suggestions/', {'field_key': 'tyre_make', 'value': 'Mojo', 'client_id': 'c1'},
                               content_type='application/json')
    codes = [post().status_code for _ in range(31)]
    assert codes[-1] == 429 and 429 not in codes[:30]


# ---------- админка ----------

@pytest.mark.django_db
def test_admin_pages_and_publish(admin_client):
    e = rotax_seeded()
    Engine.objects.filter(pk=e.pk).update(show_in_app=True)
    for url in ('/admin/setupkart/', '/admin/setupkart/publication/', '/admin/setupkart/suggestions/',
                f'/admin/website/engine/edit/{e.pk}/'):
        r = admin_client.get(url)
        assert r.status_code == 200, url
    assert 'Поле карбюратора' in admin_client.get(f'/admin/website/engine/edit/{e.pk}/').content.decode()
    admin_client.post('/admin/setupkart/publication/', {'note': 'тест'})
    assert AppCatalogVersion.objects.get().note == 'тест'


@pytest.mark.django_db
def test_admin_suggestion_actions(admin_client):
    e = rotax_seeded()
    s = AppSuggestion.objects.create(field_key='spark_plug', value='NGK BR9ES', engine=e)
    r = admin_client.post(f'/admin/setupkart/suggestions/{s.pk}/add/', {'next': 'https://evil.example/'})
    assert r['Location'] == '/admin/setupkart/suggestions/'
    assert AppEngineSparkPlug.objects.filter(engine=e, name='NGK BR9ES').exists()
    s.refresh_from_db()
    assert s.status == AppSuggestion.STATUS_ADDED

    ranged = AppSuggestion.objects.create(field_key='main_jet', value='137', engine=e)
    admin_client.post(f'/admin/setupkart/suggestions/{ranged.pk}/add/')
    ranged.refresh_from_db()
    assert ranged.status == AppSuggestion.STATUS_NEW, 'поле-диапазон не расширяется автоматически'

    hub = AppSuggestion.objects.create(field_key='hub_width_mm', value='45')
    admin_client.post(f'/admin/setupkart/suggestions/{hub.pk}/add/')
    assert '45' in expand(AppParameter.objects.get(key='hub_width_mm'))

    other = AppSuggestion.objects.create(field_key='tyre_make', value='Mojo')
    admin_client.post(f'/admin/setupkart/suggestions/{other.pk}/hide/')
    other.refresh_from_db()
    assert other.status == AppSuggestion.STATUS_HIDDEN


@pytest.mark.django_db
def test_admin_pages_forbidden_without_permission(client, django_user_model):
    user = django_user_model.objects.create_user('editor', password='x', is_staff=True)
    from django.contrib.auth.models import Permission
    user.user_permissions.add(Permission.objects.get(codename='access_admin'))
    client.force_login(user)
    assert client.get('/admin/setupkart/').status_code == 403
    assert client.post('/admin/setupkart/publication/').status_code == 403


def test_spec_models_have_no_field_named_prefix():
    """Поле «prefix» перекрывает служебный form.prefix — Wagtail ломает разметку инлайн-панели."""
    from website.models import AppEngineField, AppParameter, AppEngineSparkPlug
    for model in (AppEngineField, AppParameter, AppEngineSparkPlug):
        assert 'prefix' not in {f.name for f in model._meta.get_fields()}, model.__name__


def test_spec_models_have_no_field_named_prefix():
    """Поле «prefix» перекрывает служебный form.prefix — Wagtail ломает разметку инлайн-панели."""
    from website.models import AppEngineField, AppParameter, AppEngineSparkPlug
    for model in (AppEngineField, AppParameter, AppEngineSparkPlug):
        assert 'prefix' not in {f.name for f in model._meta.get_fields()}, model.__name__


# ---------- связь с сайтом и предложения трасс ----------

@pytest.mark.django_db
def test_config_returns_sync_interval_from_admin(client):
    data = client.get('/api/setupkart/config/').json()
    assert data['sync_interval_minutes'] == 60
    assert data['about']['site_url'] == 'https://gripline.ru'
    assert data['about']['telegram_url'] == 'https://t.me/gripline_support'
    assert 'gripline.ru' in data['about']['text']
    from website.models import AppSyncSettings
    s = AppSyncSettings.get()
    s.sync_interval_minutes = 2
    s.contact_email = 'team@example.ru'
    s.contact_telegram = 't.me/other_bot'
    s.save()
    data = client.get('/api/setupkart/config/').json()
    assert data['sync_interval_minutes'] == 2
    assert (data['about']['email'], data['about']['telegram_url']) == ('team@example.ru', 'https://t.me/other_bot')


@pytest.mark.django_db
def test_config_share_message_link_from_admin(client):
    data = client.get('/api/setupkart/config/').json()
    assert data['share'] == {
        'text': 'Веду настройки карта в приложении GripLine SetupKart — попробуй: https://gripline.ru',
        'url': 'https://gripline.ru'}
    from website.models import AppSyncSettings
    s = AppSyncSettings.get()
    s.share_text = 'Попробуй GripLine SetupKart'
    s.share_url = 'https://example.ru/app'
    s.save()
    assert client.get('/api/setupkart/config/').json()['share']['text'] == \
        'Попробуй GripLine SetupKart https://example.ru/app', 'без {link} — ссылка в конце'


@pytest.mark.django_db
def test_config_splash_image_from_admin(client):
    from wagtail.images.tests.utils import get_test_image_file
    from wagtail.images import get_image_model
    from wagtail.models import Collection
    from website.models import AppSyncSettings
    if not Collection.get_first_root_node():
        Collection.add_root(name='Root')
    data = client.get('/api/setupkart/config/').json()
    assert (data['splash'], data['splash_seconds']) == (None, 2.0)
    s = AppSyncSettings.get()
    s.splash_image = get_image_model().objects.create(title='Заставка', file=get_test_image_file(size=(60, 120)))
    s.save()
    splash = client.get('/api/setupkart/config/').json()['splash']
    assert splash['url'].endswith('.webp') and (splash['width'], splash['height']) == (60, 120)


@pytest.mark.django_db
def test_track_suggestion_needs_coordinates_and_groups_by_name(client):
    post = lambda body: client.post('/api/setupkart/suggestions/', body, content_type='application/json')
    assert post({'field_key': 'track', 'value': 'Картодром Х', 'client_id': 'c1'}).status_code == 400
    assert post({'field_key': 'track', 'value': 'Картодром Х', 'latitude': 95, 'longitude': 37, 'client_id': 'c1'}).status_code == 400
    assert post({'field_key': 'track', 'value': 'Картодром Х', 'latitude': 55.1, 'longitude': 37.2,
                 'client_id': 'c1'}).status_code == 201
    assert post({'field_key': 'track', 'value': 'Картодром Х', 'latitude': 55.3, 'longitude': 37.4,
                 'client_id': 'c2'}).status_code == 200
    s = AppSuggestion.objects.get(field_key='track')
    assert (s.count, s.latitude, s.longitude) == (2, 55.1, 37.2)


@pytest.mark.django_db
def test_admin_track_suggestion_creates_draft_track(admin_client):
    s = AppSuggestion.objects.create(field_key='track', value='Картодром Х', latitude=55.1, longitude=37.2)
    admin_client.post(f'/admin/setupkart/suggestions/{s.pk}/add/')
    t = Track.objects.get(name='Картодром Х')
    assert (t.latitude, t.longitude, t.show_in_app, t.live) == (55.1, 37.2, True, False)
    assert t.latest_revision is not None
    s.refresh_from_db()
    assert s.status == AppSuggestion.STATUS_ADDED
    page = admin_client.get('/admin/setupkart/suggestions/?status=all').content.decode()
    assert 'на карте' in page

    # такая трасса уже есть — не создаётся вторая
    dup = AppSuggestion.objects.create(field_key='track', value='картодром х', latitude=55.0, longitude=37.0)
    admin_client.post(f'/admin/setupkart/suggestions/{dup.pk}/add/')
    assert Track.objects.filter(name__iexact='картодром х').count() == 1
    dup.refresh_from_db()
    assert dup.status == AppSuggestion.STATUS_NEW


@pytest.mark.django_db
def test_sync_settings_admin_page(admin_client):
    from website.models import AppSyncSettings
    s = AppSyncSettings.get()
    assert admin_client.get('/admin/website/appsyncsettings/').status_code == 200
    assert admin_client.get(f'/admin/website/appsyncsettings/edit/{s.pk}/').status_code == 200


@pytest.mark.django_db
def test_config_pro_defaults_off_and_admin_changes(client):
    pro = client.get('/api/setupkart/config/').json()['pro']
    assert pro['enabled'] is False, 'пока выключено — в приложении всё бесплатно'
    assert pro['trial_days'] == 30
    assert pro['features']['saved_sessions'] == {'limit': 10}
    assert pro['features']['karts'] == {'limit': 1}
    assert pro['features']['compare'] == {'tier': 'pro'}
    assert pro['features']['share_setup'] == {'tier': 'free'}
    from website.models import AppProFeature, AppProSettings
    s = AppProSettings.get()
    s.enabled, s.price_text = True, '990 ₽'
    s.save()
    AppProFeature.objects.filter(key='saved_sessions').update(free_limit=None)
    AppProFeature.objects.filter(key='compare').update(tier='free')
    pro = client.get('/api/setupkart/config/').json()['pro']
    assert (pro['enabled'], pro['price']) == (True, '990 ₽')
    assert pro['features']['saved_sessions'] == {'limit': None}, 'пусто — без лимита'
    assert pro['features']['compare'] == {'tier': 'free'}


@pytest.mark.django_db
def test_pro_feature_validation():
    from django.core.exceptions import ValidationError
    from website.models import AppProFeature, AppProSettings
    s = AppProSettings.get()
    with pytest.raises(ValidationError):
        AppProFeature(settings=s, key='compare', tier='pro', free_limit=3).clean()
    with pytest.raises(ValidationError):
        AppProFeature(settings=s, key='karts', tier='pro', free_limit=1).clean()
    AppProFeature(settings=s, key='karts', tier='free', free_limit=0).clean()


@pytest.mark.django_db
def test_pro_admin_page_opens_and_saves(client, django_user_model):
    from wagtail.models import Locale, Page
    if not Locale.objects.exists():
        Locale.objects.create(language_code='ru')
    if not Page.objects.filter(depth=1).exists():
        Page.add_root(title='Root', slug='root')
    admin = django_user_model.objects.create_superuser('boss', 'b@example.ru', 'x')
    client.force_login(admin)
    assert client.get('/admin/website/appprosettings/').status_code == 200
    page = client.get('/admin/website/appprosettings/edit/1/')
    assert page.status_code == 200
    assert 'Сохранённые сессии' in page.content.decode()


@pytest.mark.django_db
def test_class_balance_thresholds_in_catalog_but_not_on_site_calculator():
    """Эталон класса (11.10.2026): в справочнике приложения — отдельно по классу; /balance/ — только общие."""
    from decimal import Decimal as D
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction
    from website.models import BalanceThreshold, RaceClass
    from website.services.balance_calc import load_thresholds
    rc = RaceClass.objects.create(name='Микро')
    BalanceThreshold.objects.create(metric='front_rear', green_min=D('42.5'), green_max=D('43.5'),
                                    yellow_min=D('42'), yellow_max=D('44'))
    BalanceThreshold.objects.create(metric='front_rear', race_class=rc, green_min=D('40.5'), green_max=D('41.5'),
                                    yellow_min=D('40'), yellow_max=D('42'))
    bal = catalog.build_payload()['balance']
    assert bal['thresholds']['front_rear']['green_min'] == 42.5
    assert bal['class_thresholds'] == {str(rc.pk): {'front_rear': {
        'green_min': 40.5, 'green_max': 41.5, 'yellow_min': 40.0, 'yellow_max': 42.0}}}
    assert load_thresholds()['front_rear'].green_min == D('42.5')
    with pytest.raises(IntegrityError), transaction.atomic():
        BalanceThreshold.objects.create(metric='front_rear', race_class=rc, green_min=1, green_max=2,
                                        yellow_min=0, yellow_max=3)
    with pytest.raises(IntegrityError), transaction.atomic():
        BalanceThreshold.objects.create(metric='front_rear', green_min=1, green_max=2, yellow_min=0, yellow_max=3)
    bad = BalanceThreshold(metric='left_right', green_min=D('49'), green_max=D('51'), yellow_min=D('49.5'),
                           yellow_max=D('52'))
    with pytest.raises(ValidationError):
        bad.clean()


def test_no_intermediate_tyres():
    """В картинге шины — слик или дождь; «промежуточных» нет (убраны 11.10.2026 по просьбе владельца)."""
    from website.models import APP_TYRE_KIND_CHOICES, TyreType
    assert [k for k, _ in APP_TYRE_KIND_CHOICES] == ['slick', 'wet']
    assert [k for k, _ in TyreType.TYRE_TYPE_CHOICES] == ['slick', 'wet']


@pytest.mark.django_db
def test_class_presets_in_payload_and_validated():
    """Рекомендации производителя по классу (таблица Rotax, 11.10.2026): в справочнике по id класса,
    значение — как в списке поля; ошибки — до публикации."""
    from website.models import AppEngineClassPreset
    e = rotax_seeded()
    mini = RaceClass.objects.create(name='RM Mini')
    e.app_race_classes.add(mini)
    e.save()
    AppEngineClassPreset.objects.create(engine=e, race_class=mini, key='main_jet', value='115',
                                        range_from='112', range_to='118')
    AppEngineClassPreset.objects.create(engine=e, race_class=mini, key='air_screw_turns', value='1.75')
    assert catalog.validation_errors() == []
    eng = next(x for x in catalog.build_payload()['engines'] if x['id'] == e.pk)
    assert eng['class_presets'] == {str(mini.pk): {
        'main_jet': {'value': '115', 'from': '112', 'to': '118'},
        'air_screw_turns': {'value': '1.75'}}}

    AppEngineClassPreset.objects.create(engine=e, race_class=mini, key='idle_turns', value='1.3')
    AppEngineClassPreset.objects.create(engine=e, race_class=mini, key='float_drop_mm', value='14')
    other = RaceClass.objects.create(name='ОК')
    AppEngineClassPreset.objects.create(engine=e, race_class=other, key='main_jet', value='120')
    errors = catalog.validation_errors()
    assert any('«1.3» нет в списке' in m for m in errors), 'не по шагу'
    assert any('Провал поплавка' in m and 'нет среди полей' in m for m in errors)
    assert any('ОК' in m and 'класс не отмечен' in m for m in errors)


@pytest.mark.django_db
def test_jet_by_rad_in_payload_and_validated():
    """Жиклёр по погоде (Rotax MAX Jetting, 12.10.2026): RAD базы, шаг и базы по классам (текущая и старая
    версия двигателя) — в справочнике; без RAD или без баз — null."""
    from website.models import AppEngineJetBase
    e = rotax_seeded()
    senior = RaceClass.objects.create(name='RM Senior')
    dd2 = RaceClass.objects.create(name='RM DD2')
    e.app_race_classes.add(senior, dd2)
    e.save()
    eng = next(x for x in catalog.build_payload()['engines'] if x['id'] == e.pk)
    assert eng['jet_by_rad'] is None
    e.app_jet_base_rad = Decimal('100')
    e.save()
    assert any('нет ни одной «Базы жиклёра' in m for m in catalog.validation_errors())
    AppEngineJetBase.objects.create(engine=e, race_class=senior, base=128)
    AppEngineJetBase.objects.create(engine=e, race_class=dd2, base=132, base_legacy=136)
    eng = next(x for x in catalog.build_payload()['engines'] if x['id'] == e.pk)
    assert eng['jet_by_rad'] == {'base_rad': 100.0, 'step': 1, 'bases': {
        str(senior.pk): {'base': 128}, str(dd2.pk): {'base': 132, 'legacy': 136}}}
    assert catalog.validation_errors() == []

    AppEngineJetBase.objects.create(engine=e, race_class=RaceClass.objects.create(name='ОК'), base=120)
    e.app_jet_base_rad = Decimal('9.2')
    e.save()
    errors = catalog.validation_errors()
    assert any('вне 50–130' in m for m in errors)
    assert any('база жиклёра «ОК»' in m and 'класс не отмечен' in m for m in errors)
    e.app_jet_base_rad = None
    e.save()
    assert any('не задан «RAD базы жиклёра»' in m for m in catalog.validation_errors())


@pytest.mark.django_db
def test_chassis_params_and_pro_features(client):
    """Поля по статье «Настройка шасси карта» (11.10.2026): диапазоны и списки — «Параметры» в админке,
    бесплатно/Pro — «Pro-версия»."""
    from website.models import AppProSettings
    AppParameter.objects.create(key='toe_mm', mode='range', min_value=Decimal('-5'), max_value=Decimal('5'),
                                step=Decimal('0.5'), default_value='0', unit='мм')
    AppParameter.objects.create(key='torsion_bar', mode='list', options_text='Нет\nГоризонтально\nВертикально',
                                default_value='Нет')
    assert catalog.validation_errors() == []
    params = catalog.build_payload()['params']
    assert params['toe_mm'] == {'key': 'toe_mm', 'label': 'Схождение, мм (− развал)', 'type': 'number',
                                'min': -5.0, 'max': 5.0, 'step': 0.5, 'decimals': 1, 'unit': 'мм', 'default': 0.0}
    assert params['torsion_bar']['options'] == ['Нет', 'Горизонтально', 'Вертикально']
    AppParameter.objects.filter(key='toe_mm').update(default_value='0.3')
    assert any('Схождение' in m for m in catalog.validation_errors()), 'по умолчанию — не по шагу'

    features = AppProSettings.get().payload()['features']
    assert features['air_density'] == {'tier': 'pro'}
    assert all(features[k] == {'tier': 'free'} for k in ('toe', 'seat_struts', 'torsion_bars', 'seat_position',
                                                         'grip_level'))


@pytest.mark.django_db
def test_chassis_advice_in_payload_and_validated():
    """Советы по поведению карта (12.10.2026): совет без правил не уходит; пары полей разворачиваются;
    «Установить» без значения и кнопка без поля — ошибки публикации."""
    from website.models import AppChassisAdvice, AppChassisRule
    a = AppChassisAdvice.objects.create(code='camber_more', title='Камбер в «+»', target='camber', action='inc')
    AppChassisAdvice.objects.create(code='no_rules', title='Без правил')
    AppChassisRule.objects.create(advice=a, symptom='understeer', phase='middle', level='weak', group='front_grip_up')
    advice = catalog.build_payload()['chassis_advice']
    assert [x['code'] for x in advice] == ['camber_more']
    assert advice[0]['fields'] == ['camber_left', 'camber_right']
    assert advice[0]['rules'] == [{'symptom': 'understeer', 'phase': 'middle', 'level': 'weak',
                                   'group': 'front_grip_up', 'ballast': 'any', 'weather': 'any', 'grip': 'any'}]
    assert catalog.validation_errors() == []
    AppChassisAdvice.objects.create(code='bad_set', title='Плохой', target='sidepods', action='set')
    AppChassisAdvice.objects.create(code='bad_target', title='Без поля', action='inc')
    errors = catalog.validation_errors()
    assert any('«Плохой»' in m and 'значение' in m for m in errors)
    assert any('«Без поля»' in m and 'поле' in m for m in errors)


@pytest.mark.django_db
def test_track_direction_compound_temp_and_fuel_mix_in_payloads():
    """12.10.2026: направление движения у трассы — в /tracks/; рабочая температура состава и пропорция смеси
    двигателя — в справочнике."""
    from website.models import AppTyreCompound, Track
    from website.setupkart.api import tracks_payload
    t = Track.objects.create(name='Трасса', show_in_app=True, live=True, latitude=55.0, longitude=37.0,
                             app_direction='ccw')
    assert next(x for x in tracks_payload()['tracks'] if x['id'] == t.pk)['direction'] == 'ccw'
    e = rotax_seeded()
    e.app_fuel_mix_ratio = Decimal('50')
    e.save()
    assert next(x for x in catalog.build_payload()['engines'] if x['id'] == e.pk)['fuel_mix_ratio'] == 50.0
    brand = TyreBrand.objects.create(name='Vega', live=True, show_in_app=True)
    AppTyreCompound.objects.create(brand=brand, name='Белая', target_temp_c=85)
    tb = next(x for x in catalog.build_payload()['tyre_brands'] if x['id'] == brand.pk)
    assert tb['compounds'][0]['target_temp_c'] == 85
