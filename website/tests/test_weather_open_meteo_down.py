"""Погода этапа (11.10.2026): страница не ходит в Open-Meteo — читает снимок из БД, который заполняет
cron-команда refresh_weather_widgets. Раньше недоступный Open-Meteo при рендере главной вешал воркер → 500."""
import datetime
from unittest import mock

import pytest
import requests
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone

from website import weather_utils
from website.models import ScheduledJobRun, WeatherWidgetSnapshot

TARGET = ('stage', 1, (43.6, 39.7, None))


@pytest.fixture(autouse=True)
def clean_cache(db):
    cache.clear()
    yield
    cache.clear()


def run_with_targets(targets, **kwargs):
    with mock.patch('website.management.commands.refresh_weather_widgets.Command._targets',
                    return_value=iter(targets)):
        call_command('refresh_weather_widgets', **kwargs)


def day(n):
    return timezone.localdate() + datetime.timedelta(days=n)


def test_render_path_never_hits_network():
    with mock.patch.object(weather_utils.requests, 'get') as get:
        assert weather_utils._get_weather_widget_for_date('stage', 1, day(60)) is None
        WeatherWidgetSnapshot.objects.create(namespace='stage', object_id=1, target_date=day(60),
                                             category='estimate', data={'temp': 12})
        assert weather_utils._get_weather_widget_for_date('stage', 1, day(60)) == {'temp': 12}
        assert get.call_count == 0


def test_past_date_with_forecast_snapshot_is_hidden():
    WeatherWidgetSnapshot.objects.create(namespace='stage', object_id=1, target_date=day(-1),
                                         category='forecast', data={'temp': 12})
    assert weather_utils._get_weather_widget_for_date('stage', 1, day(-1)) is None


def test_command_stores_and_keeps_snapshot_when_open_meteo_down():
    with mock.patch.object(weather_utils, 'fetch_climatology_estimate', return_value={'temp': 15}):
        run_with_targets([('stage', 1, (43.6, 39.7, day(60)))])
    assert WeatherWidgetSnapshot.objects.get().data == {'temp': 15}
    with mock.patch.object(weather_utils.requests, 'get',
                           side_effect=requests.exceptions.ConnectTimeout('down')) as get:
        with pytest.raises(RuntimeError):
            run_with_targets([('stage', 1, (43.6, 39.7, day(60)))], force=True)
        assert get.call_count == 1, 'после первой ошибки соединения остальные годы не запрашиваются'
    assert WeatherWidgetSnapshot.objects.get().data == {'temp': 15}, 'неудача не стирает прежний снимок'
    assert ScheduledJobRun.objects.get(name='refresh_weather_widgets').last_success_at is not None


def test_estimate_fetched_once_a_day_forecast_every_run_and_stale_removed():
    with mock.patch.object(weather_utils, 'fetch_climatology_estimate', return_value={'t': 1}) as est, \
            mock.patch.object(weather_utils, 'fetch_forecast_weather', return_value={'t': 2}) as fc:
        targets = [('stage', 1, (1, 1, day(60))), ('stage', 2, (1, 1, day(3)))]
        run_with_targets(targets)
        run_with_targets(targets)
        assert (est.call_count, fc.call_count) == (1, 2)
    run_with_targets([])
    assert not WeatherWidgetSnapshot.objects.exists(), 'снимки исчезнувших этапов удаляются'
