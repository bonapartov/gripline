"""Картинки шасси для приложения: админка (загрузка, классы, колёса), справочник, публикация."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from website.models import AppChassisImage, RaceClass
from website.setupkart import catalog, chassis_images


@pytest.fixture(autouse=True)
def _media(settings, tmp_path, db):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.BASE_URL = 'https://gripline.example'
    from wagtail.models import Collection
    if not Collection.get_first_root_node():
        Collection.add_root(name='Root')


def png(w=1000, h=1450):
    buf = io.BytesIO()
    Image.new('RGBA', (w, h), (0, 0, 0, 0)).save(buf, 'PNG')
    return SimpleUploadedFile('kart.png', buf.getvalue(), content_type='image/png')


def post(admin_client, url, **data):
    body = {'name': 'Взрослое', 'sort_order': 0, 'front_x': '', 'front_y': '', 'rear_x': '', 'rear_y': ''}
    body.update(data)
    return admin_client.post(url, body)


@pytest.mark.django_db
def test_pages_open(admin_client):
    assert admin_client.get('/admin/setupkart/chassis-images/').status_code == 200
    assert admin_client.get('/admin/setupkart/chassis-images/new/').status_code == 200


@pytest.mark.django_db
def test_create_with_image_classes_and_wheels_goes_to_catalog(admin_client):
    senior = RaceClass.objects.create(name='RM Senior')
    ok = RaceClass.objects.create(name='ОК')
    r = post(admin_client, '/admin/setupkart/chassis-images/new/', image_file=png(), classes=[senior.pk, ok.pk],
             front_x='0.17', front_y='0.32', rear_x='0.13', rear_y='0.81')
    assert r.status_code == 302
    c = AppChassisImage.objects.get()
    assert c.ready and c.image.width == 1000
    assert set(c.race_classes.values_list('name', flat=True)) == {'RM Senior', 'ОК'}
    assert admin_client.get(f'/admin/setupkart/chassis-images/{c.pk}/').status_code == 200

    item = catalog.build_payload()['chassis_images'][0]
    assert item['url'].startswith('https://gripline.example/') and item['url'].endswith('.webp')
    assert item['front'] == {'x': 0.17, 'y': 0.32} and item['rear'] == {'x': 0.13, 'y': 0.81}
    assert set(item['race_class_names']) == {'RM Senior', 'ОК'}
    assert catalog.validation_errors() == []


@pytest.mark.django_db
def test_class_moves_from_other_type_and_unchecked_class_is_released(admin_client):
    rc = RaceClass.objects.create(name='Мини')
    kids = AppChassisImage.objects.create(name='Детское')
    rc.app_chassis_image = kids
    rc.save()
    post(admin_client, '/admin/setupkart/chassis-images/new/', name='Мини', classes=[rc.pk])
    mini = AppChassisImage.objects.get(name='Мини')
    rc.refresh_from_db()
    assert rc.app_chassis_image == mini
    post(admin_client, f'/admin/setupkart/chassis-images/{mini.pk}/', name='Мини', classes=[])
    rc.refresh_from_db()
    assert rc.app_chassis_image is None


@pytest.mark.django_db
def test_form_checks(admin_client):
    url = '/admin/setupkart/chassis-images/new/'
    r = post(admin_client, url, front_x='0.2', front_y='0.3')
    assert 'Отметьте оба колеса' in r.content.decode()
    r = post(admin_client, url, front_x='0.2', front_y='0.8', rear_x='0.2', rear_y='0.3')
    assert 'Переднее колесо должно быть выше' in r.content.decode()
    r = post(admin_client, url, image_file=SimpleUploadedFile('a.png', b'not an image'))
    assert 'Не удалось прочитать картинку' in r.content.decode()
    AppChassisImage.objects.create(name='Взрослое')
    assert 'Такой тип уже есть' in post(admin_client, url, name='взрослое').content.decode()


@pytest.mark.django_db
def test_assigned_but_not_calibrated_blocks_publish_and_is_not_sent(admin_client):
    rc = RaceClass.objects.create(name='KZ2')
    post(admin_client, '/admin/setupkart/chassis-images/new/', name='KZ', image_file=png(), classes=[rc.pk])
    assert chassis_images.payload() == []
    assert any('не отмечены колёса' in e for e in catalog.validation_errors())


@pytest.mark.django_db
def test_delete_releases_classes(admin_client):
    c = AppChassisImage.objects.create(name='Взрослое')
    rc = RaceClass.objects.create(name='ОК', app_chassis_image=c)
    admin_client.post(f'/admin/setupkart/chassis-images/{c.pk}/delete/')
    rc.refresh_from_db()
    assert rc.app_chassis_image is None and not AppChassisImage.objects.exists()


@pytest.mark.django_db
def test_menu_items_present(admin_client):
    html = admin_client.get('/admin/setupkart/chassis-images/').content.decode()
    assert 'Картинки шасси' in html


@pytest.mark.django_db
def test_help_image_goes_to_catalog(admin_client):
    from wagtail.images import get_image_model
    from wagtail.models import Collection
    from website.models import AppHelpImage
    img = get_image_model()(title='колонка', file=png(600, 900), collection=Collection.get_first_root_node())
    img.save()
    AppHelpImage.objects.create(key='steering_column_hole', image=img)
    help_images = catalog.build_payload()['help_images']
    assert set(help_images) == {'steering_column_hole'}
    assert help_images['steering_column_hole']['url'].endswith('.webp')
    assert admin_client.get('/admin/website/apphelpimage/').status_code == 200
