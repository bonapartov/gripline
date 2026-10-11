"""Open-Meteo недоступен с сервера (11.10.2026): главная ждала 5 запросов по 10 с, gunicorn убивал воркер → 500.
После первой сетевой ошибки сервис не опрашивается, неудача кэшируется."""
import datetime
from unittest import mock

import pytest
import requests
from django.core.cache import cache

from website import weather_utils


@pytest.fixture(autouse=True)
def clean_cache(db):
    cache.clear()
    yield
    cache.clear()


def test_one_connection_error_stops_further_requests():
    target = datetime.date.today() + datetime.timedelta(days=60)
    with mock.patch.object(weather_utils.requests, 'get',
                           side_effect=requests.exceptions.ConnectTimeout('down')) as get:
        assert weather_utils._get_weather_widget_for_date('stage', 1, 43.6, 39.7, target) is None
        assert get.call_count == 1, 'после первой ошибки соединения остальные годы не запрашиваются'
        assert get.call_args.kwargs['timeout'] == weather_utils.OPEN_METEO_TIMEOUT
        # Повторный показ страницы — без единого запроса (кэш неудачи + «выключатель»).
        assert weather_utils._get_weather_widget_for_date('stage', 1, 43.6, 39.7, target) is None
        assert get.call_count == 1


def test_failure_cached_even_after_breaker_expires():
    target = datetime.date.today() + datetime.timedelta(days=60)
    with mock.patch.object(weather_utils.requests, 'get',
                           side_effect=requests.exceptions.ConnectionError('down')) as get:
        weather_utils._get_weather_widget_for_date('stage', 2, 43.6, 39.7, target)
        cache.delete(weather_utils.OPEN_METEO_DOWN_KEY)
        weather_utils._get_weather_widget_for_date('stage', 2, 43.6, 39.7, target)
        assert get.call_count == 1
