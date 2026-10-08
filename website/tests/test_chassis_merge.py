"""Синонимы шасси и объединение дублей (merge_chassis)."""
import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from website.models import Chassis, ChassisSocialLink
from website.setupkart import catalog


def make(name, **kw):
    return Chassis.objects.create(name=name, live=True, show_in_app=True, **kw)


def run(*args):
    out = io.StringIO()
    call_command('merge_chassis', *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_find_by_name_and_alias_case_insensitive():
    k = make('Kosmic', aliases='Cosmik, Kosmik Kart')
    assert Chassis.find_by_name(' kosmic ') == k
    assert Chassis.find_by_name('COSMIK') == k
    assert Chassis.find_by_name('kosmik kart') == k
    assert Chassis.find_by_name('Tony') is None
    assert Chassis.find_by_name('') is None


@pytest.mark.django_db
def test_dry_run_changes_nothing():
    make('Kosmic')
    make('Cosmik')
    out = run('--from', 'Cosmik', '--into', 'Kosmic')
    assert 'Ничего не изменено' in out
    assert Chassis.objects.filter(name='Cosmik').exists()


@pytest.mark.django_db
def test_merge_moves_links_adds_aliases_copies_missing_fields_and_deletes_duplicate():
    dst = make('Kosmic', aliases='Kosmik')
    src = make('Cosmik', aliases='CosmiK Kart', website='https://kosmickart.com')
    ChassisSocialLink.objects.create(page=src, network_name='ВК', link_url='https://vk.com/x')

    out = run('--from', 'cosmik', '--into', 'Kosmic', '--apply')
    assert 'Готово' in out
    assert not Chassis.objects.filter(pk=src.pk).exists()
    dst.refresh_from_db()
    assert dst.alias_list() == ['Kosmik', 'Cosmik', 'CosmiK Kart']
    assert dst.website == 'https://kosmickart.com'
    assert list(dst.social_links.values_list('network_name', flat=True)) == ['ВК']
    # Последняя ревизия (её открывает админка) уже с синонимами.
    assert dst.latest_revision.as_object().aliases == dst.aliases
    assert Chassis.find_by_name('Cosmik') == dst


@pytest.mark.django_db
def test_merge_rejects_unknown_and_same():
    make('Kosmic')
    with pytest.raises(CommandError):
        run('--from', 'Nope', '--into', 'Kosmic', '--apply')
    with pytest.raises(CommandError):
        run('--from', 'Kosmic', '--into', 'kosmic', '--apply')


@pytest.mark.django_db
def test_app_catalog_lists_aliases():
    make('Kosmic', aliases='Cosmik')
    make('Birel ART')
    chassis = catalog.build_payload()['chassis']
    # Без результатов на сайте — по алфавиту; с результатами популярные идут первыми (order_by('-n', 'name')).
    assert [c['name'] for c in chassis] == ['Birel ART', 'Kosmic']
    assert chassis[1]['aliases'] == ['Cosmik']
