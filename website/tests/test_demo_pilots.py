"""Демо-пилоты: восстановление привязки и скрытие из публичных списков."""
import json

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from accounts.models import DriverClaim, UserProfile
from website.models import Driver
from website.services.demo import without_demo


def _driver(first, last, slug):
    d = Driver(first_name=first, last_name=last, slug=slug, live=True)
    d.save()
    return d


@pytest.mark.django_db
class TestDemoPilots:
    def test_without_demo_excludes_only_demo_slugs(self):
        _driver('Пилот1', 'Демо', 'demo-pilot-1')
        real = _driver('Иван', 'Иванов', 'ivan-ivanov')
        assert list(without_demo(Driver.objects.all())) == [real]

    def test_drivers_api_hides_demo(self, client):
        _driver('Пилот1', 'Демо', 'demo-pilot-1')
        _driver('Иван', 'Иванов', 'ivan-ivanov')
        r = client.get('/drivers-api/')
        assert r.status_code == 200
        names = [i['full_name'] for i in json.loads(r.content)['items']]
        assert names == ['Иван Иванов']

    def test_relink_restores_driver_for_orphaned_claims(self):
        user = User.objects.create_user('p1', 'demo_pilot_1@email.ru', 'x')
        UserProfile.objects.get_or_create(user=user)
        DriverClaim.objects.create(
            user=user, driver=None, status='approved',
            requested_first_name='Пилот1', requested_last_name='Демо',
        )
        call_command('relink_demo_pilots')
        claim = DriverClaim.objects.get(user=user)
        assert claim.driver and claim.driver.slug == 'demo-pilot-1'
        assert UserProfile.objects.get(user=user).driver_id == claim.driver_id

    def test_relink_is_idempotent(self):
        user = User.objects.create_user('p1', 'demo_pilot_1@email.ru', 'x')
        UserProfile.objects.get_or_create(user=user)
        DriverClaim.objects.create(user=user, driver=None, status='approved',
                                   requested_first_name='Пилот1', requested_last_name='Демо')
        call_command('relink_demo_pilots')
        call_command('relink_demo_pilots')
        assert Driver.objects.filter(slug__startswith='demo-pilot-').count() == 1
        assert DriverClaim.objects.count() == 1
