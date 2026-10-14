"""Заявки на участие в админке Wagtail (applications/wagtail_hooks.py)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse
from django.utils import timezone

from applications.models import (
    Application, ApplicationApplicant, ApplicationDocument, ApplicationOption,
    ApplicationKart, ApplicationMechanic, ApplicationPayment, ApplicationPilot, StageDocument, StageOption,
)
from organizers.models import Championship, OrganizerProfile, Stage


@pytest.fixture
def app(db):
    org = OrganizerProfile.objects.create(user=User.objects.create_user('org', 'org@example.com', 'x'))
    champ = Championship.objects.create(organizer=org, title='Кубок', slug='kubok')
    stage = Stage.objects.create(championship=champ, title='1 этап', start_date=timezone.now(),
                                 end_date=timezone.now() + timedelta(hours=6))
    pilot_user = User.objects.create_user('pilot', 'pilot@example.com', 'x')
    application = Application.objects.create(stage=stage, submitted_by=pilot_user, status='submitted',
                                             entry_fee_amount=Decimal('3000'), start_number=7)
    ApplicationPilot.objects.create(application=application, first_name='Иван', last_name='Петров')
    ApplicationApplicant.objects.create(application=application, type='team', name='Команда Тест')
    doc = StageDocument.objects.create(stage=stage, name='Полис')
    ApplicationDocument.objects.create(application=application, stage_document=doc, file='application_docs/2026/10/secret.pdf')
    opt = StageOption.objects.create(stage=stage, name='Страховка', price=Decimal('500'))
    ApplicationOption.objects.create(application=application, option=opt, price_at_time=Decimal('500'))
    ApplicationPayment.objects.create(application=application, amount=Decimal('3500'))
    return application


@pytest.fixture
def staff(client, db):
    client.force_login(User.objects.create_superuser('root', 'r@example.com', 'pw'))
    return client


def test_url_names_and_group_membership(app):
    assert reverse('applications_application_modeladmin_index') == '/admin/applications/application/'


def test_list_shows_pilot_stage_and_status(staff, app):
    html = staff.get('/admin/applications/application/').content.decode()
    assert 'Иван' in html or 'Петров' in html or 'pilot@example.com' in html
    assert '1 этап' in html and 'Подана' in html


def test_list_filters_and_search(staff, app):
    base = '/admin/applications/application/'
    assert 'Подана' in staff.get(base + '?status__exact=submitted').content.decode()
    assert '1 этап' not in staff.get(base + '?status__exact=confirmed').content.decode()
    assert '1 этап' in staff.get(base + '?q=pilot%40example.com').content.decode()


def test_inspect_shows_all_related_data(staff, app):
    html = staff.get(f'/admin/applications/application/inspect/{app.pk}/').content.decode()
    for text in ('Команда Тест', 'Иван', 'Петров', 'Полис', 'Страховка', '3500', 'Заявитель', 'Пилот', 'Оплата', 'Документы'):
        assert text in html, text
    assert '3500' in html and '№' in html


def test_inspect_has_no_public_file_link(staff, app):
    """Файлы заявок отдаются только через serve_document (права заявителя/организатора)."""
    html = staff.get(f'/admin/applications/application/inspect/{app.pk}/').content.decode()
    assert 'secret.pdf' in html                      # имя файла видно
    assert '/media/application_docs' not in html     # а публичной ссылки нет
    assert 'href="/media/' not in html


def test_inspect_works_for_application_without_related_data(staff, db):
    org = OrganizerProfile.objects.create(user=User.objects.create_user('o2', 'o2@example.com', 'x'))
    champ = Championship.objects.create(organizer=org, title='К2', slug='k2')
    stage = Stage.objects.create(championship=champ, title='Э', start_date=timezone.now(), end_date=timezone.now() + timedelta(hours=1))
    bare = Application.objects.create(stage=stage, submitted_by=User.objects.create_user('p2', 'p2@example.com', 'x'))
    assert staff.get(f'/admin/applications/application/inspect/{bare.pk}/').status_code == 200
    assert 'p2@example.com' in staff.get('/admin/applications/application/').content.decode()   # без пилота — email заявителя


def test_edit_saves_card_without_filling_empty_sections(staff, app):
    """Карточка редактирует все поля регистрации; пилот обязателен, пустой необязательный
    раздел (механик) не создаётся. Этап из карточки не меняется."""
    url = f'/admin/applications/application/edit/{app.pk}/'
    assert staff.get(url).status_code == 200
    resp = staff.post(url, {
        'status': 'confirmed', 'participation': 'race', 'organizer_comment': 'Принято', 'start_number': 12,
        'race_class': '', 'entry_fee_amount': '3000', 'submitted_by_type': 'pilot',
        'pilot-last_name': 'Петров', 'pilot-first_name': 'Иван', 'pilot-citizenship': 'Россия', 'pilot-country': 'Россия',
        # пилот, заявитель и оплата у заявки есть (страница шлёт их поля заполненными), карт создаётся
        'applicant-type': 'individual', 'kart-chassis_brand': 'Tony Kart', 'kart-engine_1': 'Rotax',
        'payment-amount': '3000', 'payment-method': 'manual', 'payment-status': 'pending',
        'docs-TOTAL_FORMS': 0, 'docs-INITIAL_FORMS': 0, 'ach-TOTAL_FORMS': 0, 'ach-INITIAL_FORMS': 0,
    })
    assert resp.status_code == 302
    app.refresh_from_db()
    assert (app.status, app.organizer_comment, app.start_number) == ('confirmed', 'Принято', 12)
    assert app.entry_fee_amount == Decimal('3000') and app.stage.title == '1 этап'
    assert app.pilot.full_name == 'Петров Иван'
    assert app.kart.chassis_brand == 'Tony Kart'
    assert not ApplicationMechanic.objects.filter(application=app).exists()


def test_create_not_available_in_admin(staff, app):
    assert staff.get('/admin/applications/application/create/').status_code in (302, 403, 404)


def test_requires_permission(client, app):
    plain = User.objects.create_user('plain', password='pw')
    plain.user_permissions.add(Permission.objects.get(codename='access_admin'))
    client.force_login(plain)
    assert client.get('/admin/applications/application/').status_code in (302, 403)


def test_dashboard_links_to_wagtail_admin(db):
    from website.dashboard import data
    urls = {i['label']: i['url'] for i in data.attention_items()}
    assert urls['Заявки на участие в этапах'].startswith('/admin/applications/application/')
    assert urls['Заявки на управление командой'].startswith('/admin/teams/teamclaim/')


def test_edit_requires_pilot(staff, app):
    url = f'/admin/applications/application/edit/{app.pk}/'
    resp = staff.post(url, {
        'status': 'confirmed', 'participation': 'race', 'race_class': '', 'entry_fee_amount': '3000',
        'submitted_by_type': 'pilot', 'docs-TOTAL_FORMS': 0, 'docs-INITIAL_FORMS': 0,
        'ach-TOTAL_FORMS': 0, 'ach-INITIAL_FORMS': 0,
    })
    assert resp.status_code == 200   # форма с ошибкой, ничего не сохранено
    app.refresh_from_db()
    assert app.status != 'confirmed'
