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
    base = dict(mode='range', min_value=None, max_value=None, step=None, prefix='', options_text='',
                default_value='', allow_custom=True)
    base.update(kw)
    return AppParameter(key='hub_width_mm', **base)


def test_range_expands_with_step_precision():
    s = spec(min_value=Decimal('0.25'), max_value=Decimal('6'), step=Decimal('0.25'), default_value='1.50')
    values = expand(s)
    assert values[0] == '0.25' and values[-1] == '6.00' and len(values) == 24
    assert spec_errors(s) == {}


def test_range_with_prefix():
    s = spec(min_value=46, max_value=60, step=1, prefix='K', default_value='K50')
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
    rc = RaceClass.objects.create(name='Rotax Junior', sort_order=10)
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
    assert p['race_classes'] == [{'id': rc.pk, 'name': 'Rotax Junior', 'sort_order': 10}]
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
