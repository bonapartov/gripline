"""Рекорды трасс для приложения SetupKart: пересчёт хранит результат-рекорд, tracks/ отдаёт подробности."""
import pytest
from django.utils import timezone
from django.core.management import call_command
from wagtail.models import Page

from website.models import Chassis, Driver, EventPage, RaceClass, RaceClassResultGroup, RaceResult, Track
from website.setupkart.api import tracks_payload


@pytest.fixture
def event(db, settings):
    settings.BASE_URL = 'https://gripline.example'
    track = Track.objects.create(name='Картодром Х', live=True, show_in_app=True, latitude=55.1, longitude=37.2)
    from wagtail.models import Locale
    Locale.objects.get_or_create(language_code='ru')
    Locale.objects.get_or_create(language_code='en')
    root = Page.get_first_root_node() or Page.add_root(instance=Page(title='Root', slug='root'))
    page = root.add_child(instance=EventPage(title='Этап 1', slug='etap-1', track=track,
                                                     first_published_at=timezone.now()))
    return track, page


def result(group, driver, **laps):
    return RaceResult.objects.create(group=group, driver=driver, position=1, **laps)


@pytest.mark.django_db
def test_track_record_with_details_goes_to_app(event):
    track, page = event
    rc = RaceClass.objects.create(name='Rotax Junior', sort_order=10)
    group = RaceClassResultGroup.objects.create(page=page, race_class=rc, air_temperature=18.4, humidity=60,
                                                precipitation=0)
    ivan = Driver.objects.create(first_name='Иван', last_name='Петров', slug='ivan-petrov')
    oleg = Driver.objects.create(first_name='Олег', last_name='Сидоров', slug='oleg')
    result(group, ivan, qual_best_lap_ms=47215, best_lap_ms=47500,
           chassis_new=Chassis.objects.create(name='Tony Kart'))
    result(group, oleg, best_lap_ms=47900)
    other = Track.objects.create(name='Без рекордов', live=True, show_in_app=True, latitude=1, longitude=2)

    call_command('update_track_records', verbosity=0)
    by_id = {t['id']: t for t in tracks_payload()['tracks']}
    assert by_id[other.pk]['records'] == []
    rec = by_id[track.pk]['records'][0]
    assert rec['lap_ms'] == 47215 and rec['class_name'] == 'Rotax Junior'
    assert rec['driver'] == 'Иван Петров' and rec['driver_url'] == 'https://gripline.example/drivers/ivan-petrov/'
    assert rec['session'] == 'Квалификация' and rec['chassis'] == 'Tony Kart'
    assert rec['weather'] == '+18 °C, влажность 60%, без осадков'
    assert rec['event'] == 'Этап 1'  # event_url — только при настроенном Site (на проде есть)
    assert 'engine' not in rec and 'tyre' not in rec, 'пустые поля не отдаются'


@pytest.mark.django_db
def test_demo_pilot_record_is_not_sent(event):
    track, page = event
    group = RaceClassResultGroup.objects.create(page=page, race_class=RaceClass.objects.create(name='Mini'))
    result(group, Driver.objects.create(first_name='Демо', last_name='Пилот', slug='demo-pilot-1'), best_lap_ms=50000)
    call_command('update_track_records', verbosity=0)
    assert next(t for t in tracks_payload()['tracks'] if t['id'] == track.pk)['records'] == []
