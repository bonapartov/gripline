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
