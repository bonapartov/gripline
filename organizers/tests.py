from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import DriverClaim
from applications.models import (
    Application, ApplicationDocument, ApplicationOption, ChampionshipDocument, ChampionshipOption,
    StageDocument, StageOption,
)
from website.models import RaceClass

from .models import Championship, OrganizerProfile, Stage
from .views import _sync_championship_docs_to_stages, _sync_championship_opts_to_stages


class OrganizerFixture(TestCase):
    def setUp(self):
        # --no-migrations → дерева Wagtail нет, а шаблоны кабинета читают LayoutSettings сайта.
        from django.conf import settings
        from wagtail.coreutils import get_supported_content_language_variant
        from wagtail.models import Locale, Page, Site
        Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
        Site.objects.create(hostname='testserver', root_page=Page.add_root(title='Root', slug='root'),
                            is_default_site=True)
        self.org_user = User.objects.create_user(username='org', email='org@example.com', password='x')
        self.organizer = OrganizerProfile.objects.create(user=self.org_user, status='active')
        self.championship = Championship.objects.create(
            organizer=self.organizer, title='Кубок', slug='kubok',
            registration_mode=Championship.REG_MODE_ALL,
        )
        start = timezone.now() + timedelta(days=10)
        self.stage = Stage.objects.create(
            championship=self.championship, title='Этап 1', start_date=start, end_date=start + timedelta(hours=8),
        )
        self.pilot = User.objects.create_user(username='pilot', email='pilot@example.com', password='x')
        self.mini = RaceClass.objects.create(name='Мини')
        self.junior = RaceClass.objects.create(name='Юниор')
        self.championship.race_classes.set([self.mini, self.junior])

    def application(self, **kw):
        kw.setdefault('stage', self.stage)
        kw.setdefault('submitted_by', self.pilot)
        kw.setdefault('race_class', self.mini)
        return Application.objects.create(**kw)


@override_settings(MEDIA_ROOT='/tmp/gripline-test-media')
class ChampionshipSyncKeepsParticipantDataTests(OrganizerFixture):
    """Правка общих настроек чемпионата раньше удаляла документы и опции этапов
    и создавала заново — каскадом пропадали загрузки и выбранные опции заявок."""

    def setUp(self):
        super().setUp()
        self.passport = ChampionshipDocument.objects.create(championship=self.championship, name='Паспорт')
        self.tyres = ChampionshipOption.objects.create(championship=self.championship, name='Шины', price=5000)
        _sync_championship_docs_to_stages(self.championship)
        _sync_championship_opts_to_stages(self.championship)
        self.stage_passport = self.stage.required_documents.get()
        self.stage_tyres = self.stage.options.get()
        self.app = self.application()
        self.upload = ApplicationDocument.objects.create(
            application=self.app, stage_document=self.stage_passport, status='verified',
            file=SimpleUploadedFile('p.jpg', b'x'),
        )
        self.chosen = ApplicationOption.objects.create(application=self.app, option=self.stage_tyres, price_at_time=5000)

    def test_adding_document_keeps_uploads(self):
        ChampionshipDocument.objects.create(championship=self.championship, name='Медсправка', order=1)
        _sync_championship_docs_to_stages(self.championship)
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.status, 'verified')
        self.assertEqual(self.upload.stage_document_id, self.stage_passport.id)
        self.assertEqual(sorted(self.stage.required_documents.values_list('name', flat=True)), ['Медсправка', 'Паспорт'])

    def test_editing_document_updates_in_place(self):
        self.passport.description = 'Разворот с фото'
        self.passport.save()
        _sync_championship_docs_to_stages(self.championship)
        self.stage_passport.refresh_from_db()
        self.assertEqual(self.stage_passport.description, 'Разворот с фото')
        self.assertTrue(ApplicationDocument.objects.filter(pk=self.upload.pk).exists())

    def test_removed_document_with_uploads_is_deactivated_not_deleted(self):
        self.passport.delete()
        _sync_championship_docs_to_stages(self.championship)
        self.stage_passport.refresh_from_db()
        self.assertFalse(self.stage_passport.is_active)
        self.assertTrue(ApplicationDocument.objects.filter(pk=self.upload.pk).exists())

    def test_removed_document_without_uploads_is_deleted(self):
        extra = ChampionshipDocument.objects.create(championship=self.championship, name='Страховка')
        _sync_championship_docs_to_stages(self.championship)
        extra.delete()
        _sync_championship_docs_to_stages(self.championship)
        self.assertFalse(self.stage.required_documents.filter(name='Страховка').exists())

    def test_option_changes_keep_chosen_options(self):
        ChampionshipOption.objects.create(championship=self.championship, name='Транспондер', price=500, order=1)
        _sync_championship_opts_to_stages(self.championship)
        self.assertTrue(ApplicationOption.objects.filter(pk=self.chosen.pk).exists())
        self.tyres.delete()
        _sync_championship_opts_to_stages(self.championship)
        self.stage_tyres.refresh_from_db()
        self.assertFalse(self.stage_tyres.is_active)
        self.assertEqual(self.app.get_total_amount(), 5000)

    def test_legacy_stage_rows_without_source_matched_by_name(self):
        """Строки этапов, скопированные до появления ссылки source, не пересоздаются."""
        StageDocument.objects.filter(pk=self.stage_passport.pk).update(source=None)
        _sync_championship_docs_to_stages(self.championship)
        self.assertEqual(self.stage.required_documents.get().pk, self.stage_passport.pk)


class RegistrationClosedTests(OrganizerFixture):
    def test_open_by_default(self):
        self.assertIsNone(self.stage.registration_closed_reason())

    def test_deadline_passed_closes_without_late_registration(self):
        self.stage.registration_deadline = timezone.now() - timedelta(hours=1)
        self.stage.save()
        self.assertIn('Срок регистрации истёк', self.stage.registration_closed_reason())
        self.stage.late_registration_allowed = True
        self.stage.save()
        self.assertIsNone(self.stage.registration_closed_reason())

    def test_participant_limit(self):
        self.stage.max_participants = 1
        self.stage.save()
        self.application(status='rejected')
        self.assertIsNone(self.stage.registration_closed_reason())
        self.application(status='submitted')
        self.assertIn('Мест нет', self.stage.registration_closed_reason())

    def test_apply_page_refuses_after_deadline(self):
        self.stage.registration_deadline = timezone.now() - timedelta(hours=1)
        self.stage.save()
        self.client.force_login(self.pilot)
        resp = self.client.get(f'/applications/apply/{self.stage.id}/')
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('/applications/apply/', resp.url)


class DuplicateApplicationTests(OrganizerFixture):
    def test_second_application_in_same_class_redirects_to_first(self):
        DriverClaim.objects.create(user=self.pilot, requested_first_name='И', requested_last_name='П', status='approved')
        first = self.application(status='submitted')
        self.client.force_login(self.pilot)
        resp = self.client.post(f'/applications/apply/{self.stage.id}/', {'race_class': self.mini.id})
        self.assertRedirects(resp, f'/applications/{first.id}/', fetch_redirect_response=False)
        self.assertEqual(Application.objects.filter(stage=self.stage).count(), 1)


class OrganizerAccessTests(OrganizerFixture):
    def test_delete_requires_post(self):
        self.client.force_login(self.org_user)
        resp = self.client.get(f'/organizers/stage/delete/{self.stage.id}/')
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Stage.objects.filter(pk=self.stage.pk).exists())
        resp = self.client.get(f'/organizers/championship/delete/{self.championship.id}/')
        self.assertEqual(resp.status_code, 405)
        self.client.post(f'/organizers/stage/delete/{self.stage.id}/')
        self.assertFalse(Stage.objects.filter(pk=self.stage.pk).exists())

    def test_pending_organizer_cannot_create(self):
        self.organizer.status = 'pending'
        self.organizer.save()
        self.client.force_login(self.org_user)
        resp = self.client.get('/organizers/championship/create/')
        self.assertRedirects(resp, '/organizers/pending/', fetch_redirect_response=False)
        resp = self.client.post(f'/organizers/stage/create/{self.championship.id}/', {'title': 'X'})
        self.assertRedirects(resp, '/organizers/pending/', fetch_redirect_response=False)

    def test_rejected_organizer_cannot_judge_applications(self):
        app = self.application(status='submitted')
        self.organizer.status = 'rejected'
        self.organizer.save()
        self.client.force_login(self.org_user)
        self.client.post(f'/applications/{app.id}/action/', {'action': 'confirm'})
        app.refresh_from_db()
        self.assertEqual(app.status, 'submitted')


class NotificationAndNumberTests(OrganizerFixture):
    def test_organizer_notified_on_submit(self):
        app = self.application(status='draft')
        self.client.force_login(self.pilot)
        self.client.post(f'/applications/{app.id}/submit/')
        app.refresh_from_db()
        self.assertEqual(app.status, 'submitted')
        self.assertEqual([m.to for m in mail.outbox], [['org@example.com']])
        self.assertIn(f'Новая заявка #{app.id}', mail.outbox[0].subject)

    def test_deactivated_required_document_does_not_block_submit(self):
        app = self.application(status='draft')
        doc = StageDocument.objects.create(stage=self.stage, name='Старый', is_active=False)
        ApplicationDocument.objects.create(application=app, stage_document=doc, status='pending')
        self.client.force_login(self.pilot)
        self.client.post(f'/applications/{app.id}/submit/')
        app.refresh_from_db()
        self.assertEqual(app.status, 'submitted')

    def test_reassign_number_checked_within_class(self):
        self.application(start_number=22, race_class=self.junior, status='confirmed')
        mine = self.application(start_number=11, race_class=self.mini, status='confirmed')
        self.client.force_login(self.org_user)
        url = f'/organizers/stage/{self.stage.id}/numbers/reassign/'
        self.assertTrue(self.client.post(url, {'app_id': mine.id, 'new_number': 22}).json()['success'])
        self.application(start_number=33, race_class=self.mini, status='submitted')
        self.assertFalse(self.client.post(url, {'app_id': mine.id, 'new_number': 33}).json()['success'])


class TrainingSessionTests(OrganizerFixture):
    """УТС перед этапом с отдельными 3-значными номерами для «только УТС»; «УТС + этап»
    и «только этап» — номера этапа (10–99); «УТС + этап» платит оба взноса."""

    def setUp(self):
        super().setUp()
        self.stage.entry_fee = 8000
        self.stage.has_training = True
        self.stage.training_fee = 3000
        self.stage.training_number_digits = 3
        self.stage.save()

    def test_choices_and_fees(self):
        self.assertEqual([c for c, _ in self.stage.participation_choices()], ['race', 'training_race', 'training'])
        self.assertEqual(self.stage.fee_for('race'), 8000)
        self.assertEqual(self.stage.fee_for('training_race'), 11000)
        self.assertEqual(self.stage.fee_for('training'), 3000)

    def test_number_ranges(self):
        self.assertEqual(self.stage.number_range('training'), range(100, 1000))
        self.assertEqual(self.stage.number_range('training_race'), range(10, 100))
        self.assertEqual(self.stage.get_available_numbers(self.mini, 'training')[0], 100)
        self.assertEqual(self.stage.get_available_numbers(self.mini, 'race')[-1], 99)

    def test_shared_number_pool_when_formats_match(self):
        """Формат номеров УТС совпадает с этапом — номера общие: «только УТС» не может взять
        номер, занятый участником этапа в том же классе, а в другом классе — может."""
        self.stage.training_number_digits = 2
        self.stage.save()
        self.assertFalse(self.stage.separate_training_numbers())
        self.assertEqual(self.stage.number_range('training'), range(10, 100))
        self.application(participation='race', start_number=17, status='confirmed')
        self.assertNotIn(17, self.stage.get_available_numbers(self.mini, 'training'))
        self.assertIn(17, self.stage.get_available_numbers(self.junior, 'training'))

    def test_shared_pool_numbers_page_has_one_grid(self):
        self.stage.training_number_digits = 2
        self.stage.save()
        self.client.force_login(self.org_user)
        resp = self.client.get(f'/organizers/stage/{self.stage.id}/numbers/')
        self.assertEqual(len(resp.context['grids']), 1)
        self.assertEqual(resp.context['total_all'], 90)

    def test_three_digit_stage_with_two_digit_training(self):
        self.stage.start_number_digits, self.stage.training_number_digits = 3, 2
        self.stage.save()
        self.assertEqual(self.stage.number_range('training_race'), range(100, 1000))
        self.assertEqual(self.stage.number_range('training'), range(10, 100))

    def test_without_training_only_race_and_stage_format(self):
        self.stage.has_training = False
        self.stage.start_number_digits = 3
        self.stage.save()
        self.assertEqual([c for c, _ in self.stage.participation_choices()], ['race'])
        self.assertEqual(self.stage.fee_for('training'), 8000)
        self.assertEqual(self.stage.number_range('training'), range(100, 1000))
        self.assertEqual(self.stage.number_range('race'), range(100, 1000))

    def test_numbers_api_respects_participation(self):
        resp = self.client.get(f'/applications/apply/{self.stage.id}/numbers/',
                               {'class_id': self.mini.id, 'participation': 'training'})
        self.assertEqual(resp.json()['numbers'][0], 100)

    def test_limit_counts_only_race_participants(self):
        self.stage.max_participants = 1
        self.stage.save()
        self.application(participation='training', status='submitted')
        self.assertIsNone(self.stage.registration_closed_reason())
        self.application(participation='training_race', status='submitted')
        self.assertIn('Мест нет', self.stage.registration_closed_reason())

    def test_reassign_checks_participation_range(self):
        app = self.application(participation='training', start_number=150, status='confirmed')
        self.client.force_login(self.org_user)
        url = f'/organizers/stage/{self.stage.id}/numbers/reassign/'
        self.assertFalse(self.client.post(url, {'app_id': app.id, 'new_number': 15}).json()['success'])
        self.assertTrue(self.client.post(url, {'app_id': app.id, 'new_number': 151}).json()['success'])

    def test_numbers_page_shows_two_grids(self):
        self.client.force_login(self.org_user)
        resp = self.client.get(f'/organizers/stage/{self.stage.id}/numbers/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['grids']), 2)
        self.assertEqual(resp.context['total_all'], 990)


class AdminCardsTests(OrganizerFixture):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'x')
        self.client.force_login(self.admin)

    def test_application_card_edits_all_registration_sections(self):
        from applications.models import ApplicationPayment, ApplicationPilot, StageOption
        app = self.application(status='submitted', entry_fee_amount=1000)
        ApplicationPilot.objects.create(application=app, first_name='Иван', last_name='Петров')
        ApplicationPayment.objects.create(application=app, amount=1000)
        opt = StageOption.objects.create(stage=self.stage, name='Транспондер', price=500)
        url = f'/admin/applications/application/edit/{app.id}/'
        self.assertEqual(self.client.get(url).status_code, 200)
        data = {
            'status': 'confirmed', 'participation': 'race', 'race_class': self.junior.id, 'start_number': 42,
            'entry_fee_amount': 1000, 'submitted_by_type': 'pilot', 'organizer_comment': 'ок',
            'pilot-last_name': 'Петров', 'pilot-first_name': 'Иван', 'pilot-citizenship': 'Россия',
            'pilot-country': 'Россия', 'pilot-city': 'Гатчина',
            'kart-chassis_brand': 'Tony Kart', 'kart-engine_1': 'Rotax',
            'payment-amount': 1500, 'payment-method': 'manual', 'payment-status': 'verified',
            'docs-TOTAL_FORMS': 0, 'docs-INITIAL_FORMS': 0,
            'ach-TOTAL_FORMS': 1, 'ach-INITIAL_FORMS': 0,
            'ach-0-competition_name': 'Кубок СПб', 'ach-0-year': 2025, 'ach-0-achievement': '1 место', 'ach-0-order': 0,
            'options': [opt.id],
        }
        resp = self.client.post(url, data)
        if resp.status_code != 302:
            ctx = resp.context
            self.fail([ctx['form'].errors] + [s['form'].errors for s in ctx['related']['sections']]
                      + [ctx['related']['documents'].errors, ctx['related']['achievements'].errors])
        app.refresh_from_db()
        self.assertEqual((app.status, app.start_number, app.race_class_id), ('confirmed', 42, self.junior.id))
        self.assertEqual(app.pilot.city, 'Гатчина')
        self.assertEqual(app.kart.chassis_brand, 'Tony Kart')
        self.assertFalse(hasattr(app, 'mechanic') and app.mechanic.pk)
        self.assertEqual(app.payment.status, 'verified')
        self.assertEqual(app.achievements.get().competition_name, 'Кубок СПб')
        self.assertEqual(list(app.selected_options.values_list('option_id', flat=True)), [opt.id])

    def test_organizer_card_edits_account_and_profile(self):
        url = f'/admin/organizers/organizerprofile/edit/{self.organizer.id}/'
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url, {
            'user-last_name': 'Сидоров', 'user-first_name': 'Пётр', 'user-email': 'new-org@example.com',
            'status': 'active', 'phone': '+79990000000', 'telegram': '@org', 'website': '',
            'commission_percent': '', 'commission_payer': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.org_user.refresh_from_db()
        self.organizer.refresh_from_db()
        self.assertEqual((self.org_user.last_name, self.org_user.email), ('Сидоров', 'new-org@example.com'))
        self.assertEqual(self.organizer.phone, '+79990000000')

    def test_organizer_email_must_be_unique(self):
        url = f'/admin/organizers/organizerprofile/edit/{self.organizer.id}/'
        resp = self.client.post(url, {
            'user-last_name': 'X', 'user-first_name': 'Y', 'user-email': 'pilot@example.com', 'status': 'active',
        })
        self.assertEqual(resp.status_code, 200)
        self.org_user.refresh_from_db()
        self.assertEqual(self.org_user.email, 'org@example.com')


class TrainingApplyFormTests(OrganizerFixture):
    def test_apply_form_offers_three_options_with_prices(self):
        # формат номеров УТС по умолчанию совпадает с этапом — общая база номеров
        self.stage.entry_fee, self.stage.has_training, self.stage.training_fee = 8000, True, 3000
        self.stage.save()
        DriverClaim.objects.create(user=self.pilot, requested_first_name='И', requested_last_name='П', status='approved')
        self.client.force_login(self.pilot)
        resp = self.client.get(f'/applications/apply/{self.stage.id}/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for label in ('Только этап — 8000 ₽', 'УТС + этап — 11000 ₽', 'Только УТС — 3000 ₽'):
            self.assertIn(label, html)


class DashboardHeaderTests(OrganizerFixture):
    def test_support_block_in_header_left_of_organizer(self):
        from organizers.models import OrganizerSettings
        OrganizerSettings.objects.create(support_phone='+7 900 000-00-00', support_email='help@example.com')
        self.org_user.first_name, self.org_user.last_name = 'Иван', 'Петров'
        self.org_user.save()
        self.client.force_login(self.org_user)
        html = self.client.get('/organizers/dashboard/').content.decode()
        head = html[html.index('cabinet-head'):html.index('two-columns">')]
        self.assertLess(head.index('help@example.com'), head.index('Иван Петров'))
        self.assertIn('tel:+7 900 000-00-00', head)
        self.assertNotIn('Условия оплаты', html)   # оплата выключена — левой колонки нет

    def test_champ_and_stage_actions_share_one_layout(self):
        self.client.force_login(self.org_user)
        html = self.client.get('/organizers/dashboard/').content.decode()
        self.assertEqual(html.count('class="item-actions"'), 2)   # чемпионат и его этап
        self.assertIn('Добавить этап', html)
        self.assertIn(f'/organizers/stage/{self.stage.id}/registrations/', html)
        self.assertIn(f'/organizers/stage/{self.stage.id}/numbers/', html)
