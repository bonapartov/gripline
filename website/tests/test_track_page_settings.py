"""Общие настройки страницы трассы: размер метки-карта в 3D (админка → Трассы → Настройки страницы)."""
import pytest
from django.core.exceptions import ValidationError

from website.models import TrackPageSettings
from website.services import track_page


@pytest.mark.django_db
def test_kart_scale_defaults_to_three_and_reaches_3d_data():
    assert TrackPageSettings.get().kart_scale == 3
    s = TrackPageSettings.get()
    s.kart_scale = 2.5
    s.save()
    assert track_page._kart_scale() == 2.5


@pytest.mark.django_db
@pytest.mark.parametrize('value', [0.5, 6])
def test_kart_scale_out_of_range_is_rejected(value):
    s = TrackPageSettings.get()
    s.kart_scale = value
    with pytest.raises(ValidationError):
        s.full_clean()


@pytest.mark.django_db
def test_saving_settings_purges_cached_track_pages(monkeypatch):
    calls = []
    monkeypatch.setattr('wagtailcache.cache.clear_cache', lambda urls=None: calls.append(urls))
    TrackPageSettings.get().save()
    assert any(u and any('/tracks/' in p for p in u) for u in calls)
