"""Постоянные типы документов, хранилище ЛК пилота и напоминания о сроке."""
import shutil
import tempfile
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from accounts import telegram_link
from accounts.models import PilotDocument
from organizers.forms import StageDocumentForm
from website.models import FeedbackBotSettings

from . import document_kinds, reminders, vault
from .models import (Application, ApplicationPilot, DocumentReminder, DocumentReminderSettings,
                     StageDocument)
from .test_wizard import WizardFixture

LICENSE, POA, INSURANCE = document_kinds.LICENSE, document_kinds.POWER_OF_ATTORNEY, document_kinds.INSURANCE


class MediaMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()


def pdf(content=b'%PDF-1.4 test'):
    return SimpleUploadedFile('scan.pdf', content, content_type='application/pdf')


class DocumentKindTests(WizardFixture):
    def test_fixed_kind_sets_name_and_flags(self):
        doc = StageDocument.objects.create(stage=self.stage, kind=POA, name='что угодно', minors_only=False)
        self.assertEqual((doc.name, doc.minors_only, doc.has_expiry_date), ('Доверенность', True, True))

    def test_form_requires_name_only_for_other(self):
        form = StageDocumentForm({'kind': 'other', 'name': '', 'required': 'on'})
        self.assertFalse(form.is_valid())
        form = StageDocumentForm({'kind': LICENSE, 'name': '', 'required': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['name'], 'Лицензия')

    def test_form_rejects_second_document_of_same_kind(self):
        form = StageDocumentForm({'kind': LICENSE, 'required': 'on'}, existing_kinds=[LICENSE])
        self.assertFalse(form.is_valid())

    def test_kind_by_old_names(self):
        self.assertEqual(document_kinds.kind_by_name('Мед  справка'), document_kinds.MEDICAL)
        self.assertEqual(document_kinds.kind_by_name('Анкета'), document_kinds.OTHER)


class VaultTests(MediaMixin, WizardFixture):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('pilot@example.com', 'pilot@example.com', 'pw')
        self.profile = self.user.profile
        self.license = StageDocument.objects.create(stage=self.stage, kind=LICENSE)
        self.poa = StageDocument.objects.create(stage=self.stage, kind=POA)

    def application(self, birth=date(2000, 1, 1)):
        app = Application.objects.create(stage=self.stage, submitted_by=self.user, race_class=self.mini,
                                         status='draft')
        ApplicationPilot.objects.create(application=app, last_name='Новиков', first_name='Пётр',
                                        birth_date=birth)
        return app

    def vault_doc(self, kind, expiry, **extra):
        return PilotDocument.objects.create(profile=self.profile, kind=kind, name=document_kinds.label(kind),
                                            file=pdf(), expiry_date=expiry, **extra)

    def test_filled_from_vault_by_kind_when_valid_through_stage(self):
        saved = self.vault_doc(LICENSE, self.stage.end_date.date() + timedelta(days=30))
        app = self.application()
        vault.create_document_rows(app, is_minor=False)
        row = app.documents.get(stage_document=self.license)
        self.assertEqual((row.status, row.vault_document, row.expiry_date), ('uploaded', saved, saved.expiry_date))
        self.assertTrue(row.file.name)
        self.assertFalse(app.documents.filter(stage_document=self.poa).exists())   # взрослому доверенность не нужна

    def test_not_filled_if_expires_before_stage_ends(self):
        last_day = vault.stage_last_day(self.stage)
        self.vault_doc(LICENSE, last_day - timedelta(days=1))   # не дотягивает до последнего дня этапа
        app = self.application()
        states = {doc.kind: state for doc, _, state in vault.preview(self.stage, self.profile, False)}
        self.assertEqual(states[LICENSE], 'expired')
        vault.create_document_rows(app, is_minor=False)
        self.assertEqual(app.documents.get(stage_document=self.license).status, 'pending')

    def test_valid_on_last_day_of_stage_is_enough(self):
        self.vault_doc(LICENSE, vault.stage_last_day(self.stage))
        states = {doc.kind: state for doc, _, state in vault.preview(self.stage, self.profile, False)}
        self.assertEqual(states[LICENSE], 'ok')

    def test_rejected_vault_document_not_filled(self):
        self.vault_doc(LICENSE, date(2099, 1, 1), rejected_at=timezone.now())
        app = self.application()
        vault.create_document_rows(app, is_minor=False)
        self.assertEqual(app.documents.get(stage_document=self.license).status, 'pending')

    def test_minor_gets_power_of_attorney_row(self):
        app = self.application(birth=date.today() - timedelta(days=365 * 12))
        vault.create_document_rows(app, is_minor=True)
        self.assertTrue(app.documents.filter(stage_document=self.poa).exists())

    def test_upload_to_application_saves_to_vault_and_replaces_previous(self):
        old = self.vault_doc(LICENSE, date(2026, 1, 1))
        app = self.application()
        app.status = 'submitted'
        app.save()
        vault.create_document_rows(app, is_minor=False)
        row = app.documents.get(stage_document=self.license)
        self.client.force_login(self.user)
        resp = self.client.post(f'/applications/document/{row.id}/upload/',
                                {'file': pdf(b'new'), 'expiry_date': '2027-12-31'},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200, resp.content)
        current = PilotDocument.objects.get(profile=self.profile, kind=LICENSE)
        self.assertNotEqual(current.pk, old.pk)
        self.assertEqual(current.expiry_date, date(2027, 12, 31))
        row.refresh_from_db()
        self.assertEqual(row.vault_document, current)

    def test_upload_of_fixed_kind_requires_expiry(self):
        app = self.application()
        vault.create_document_rows(app, is_minor=False)
        row = app.documents.get(stage_document=self.license)
        self.client.force_login(self.user)
        resp = self.client.post(f'/applications/document/{row.id}/upload/', {'file': pdf()},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PilotDocument.objects.exists())

    def test_other_kind_not_saved_to_vault(self):
        other = StageDocument.objects.create(stage=self.stage, name='Анкета', has_expiry_date=False)
        app = self.application()
        vault.create_document_rows(app, is_minor=False)
        row = app.documents.get(stage_document=other)
        row.file = pdf()
        row.save()
        self.assertIsNone(vault.save_from_application(row))
        self.assertFalse(PilotDocument.objects.exists())

    def test_organizer_reject_marks_vault_document(self):
        saved = self.vault_doc(LICENSE, date(2099, 1, 1))
        app = self.application()
        vault.create_document_rows(app, is_minor=False)
        row = app.documents.get(stage_document=self.license)
        self.client.force_login(self.organizer.user)
        self.client.post(f'/applications/document/{row.id}/verify/', {'action': 'reject', 'comment': 'нечитаемо'})
        saved.refresh_from_db()
        self.assertIsNotNone(saved.rejected_at)
        self.assertEqual(saved.rejected_comment, 'нечитаемо')

    def test_team_application_does_not_touch_vault(self):
        self.vault_doc(LICENSE, date(2099, 1, 1))
        app = self.application()
        app.submitted_by_type = 'team'
        app.save()
        vault.create_document_rows(app, is_minor=False)
        self.assertEqual(app.documents.get(stage_document=self.license).status, 'pending')


class ProfileVaultUploadTests(MediaMixin, WizardFixture):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('pilot@example.com', 'pilot@example.com', 'pw')
        self.client.force_login(self.user)

    def upload(self, **data):
        return self.client.post('/accounts/documents/upload/', {'file': pdf(), **data},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_fixed_kind_replaces_previous_and_requires_expiry(self):
        self.assertEqual(self.upload(kind=INSURANCE).status_code, 400)
        first = self.upload(kind=INSURANCE, expiry_date='2026-12-01').json()
        second = self.upload(kind=INSURANCE, expiry_date='2027-12-01').json()
        self.assertEqual(second['replaced'], [first['id']])
        self.assertEqual(list(PilotDocument.objects.values_list('kind', 'name')), [(INSURANCE, 'Страховка')])

    def test_other_kind_needs_name(self):
        self.assertEqual(self.upload(kind='other').status_code, 400)
        self.assertEqual(self.upload(kind='other', name='Паспорт').status_code, 200)

    def test_calendar_file_only_for_owner(self):
        doc = PilotDocument.objects.create(profile=self.user.profile, kind=LICENSE, name='Лицензия',
                                           file=pdf(), expiry_date=date.today() + timedelta(days=40))
        resp = self.client.get(f'/accounts/documents/{doc.id}/calendar.ics')
        self.assertEqual(resp['Content-Type'], 'text/calendar; charset=utf-8')
        body = resp.content.decode()
        self.assertEqual(body.count('BEGIN:VEVENT'), 4)   # 30, 10, 1 день и день окончания
        self.assertIn('TRIGGER;RELATED=START:PT9H', body)
        other = User.objects.create_user('x@example.com', 'x@example.com', 'pw')
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'/accounts/documents/{doc.id}/calendar.ics').status_code, 404)


class ReminderTests(MediaMixin, WizardFixture):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('pilot@example.com', 'pilot@example.com', 'pw')
        self.profile = self.user.profile
        self.today = date(2026, 10, 15)

    def doc(self, days_left, kind=LICENSE):
        return PilotDocument.objects.create(profile=self.profile, kind=kind, name=document_kinds.label(kind),
                                            file=pdf(), expiry_date=self.today + timedelta(days=days_left))

    def run_on(self, day):
        return reminders.send_all(today=day)

    def test_thresholds_send_once_each(self):
        doc = self.doc(25)
        self.assertEqual(self.run_on(self.today)[0], 1)           # попал в «30 дней»
        self.assertEqual(self.run_on(self.today)[0], 0)           # повторно — нет
        self.assertEqual(self.run_on(self.today + timedelta(days=15))[0], 1)   # осталось 10
        self.assertEqual(self.run_on(self.today + timedelta(days=24))[0], 1)   # остался 1 день
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(set(DocumentReminder.objects.filter(document=doc).values_list('days_before', flat=True)),
                         {30, 10, 1})

    def test_late_upload_gets_single_reminder(self):
        self.doc(5)
        self.assertEqual(self.run_on(self.today)[0], 1)
        self.assertEqual(self.run_on(self.today + timedelta(days=1))[0], 0)   # 30 и 10 уже «пройдены»
        self.assertIn('через 5 дней', mail.outbox[0].subject)

    def test_new_expiry_restarts_reminders(self):
        doc = self.doc(5)
        self.run_on(self.today)
        doc.expiry_date = self.today + timedelta(days=200)
        doc.save()
        self.assertEqual(self.run_on(self.today + timedelta(days=175))[0], 1)

    def test_minor_parent_also_gets_email(self):
        self.profile.birth_date = date(2014, 5, 1)
        self.profile.parent_email = 'mom@example.com'
        self.profile.save()
        self.doc(1)
        self.run_on(self.today)
        self.assertEqual(sorted(mail.outbox[0].to), ['mom@example.com', 'pilot@example.com'])

    def test_disabled_and_dry_run_send_nothing(self):
        self.doc(1)
        self.assertEqual(reminders.send_all(today=self.today, dry_run=True)[0], 0)
        cfg = DocumentReminderSettings.get()
        cfg.enabled = False
        cfg.save()
        self.assertEqual(self.run_on(self.today)[0], 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(DocumentReminder.objects.exists())

    def test_telegram_sent_and_blocked_bot_turns_it_off(self):
        self.profile.telegram_id, self.profile.telegram_notifications = 777, True
        self.profile.save()
        self.doc(1)
        with mock.patch('website.feedback.notify.send_user_message', return_value='blocked') as send:
            self.run_on(self.today)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], 777)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.telegram_notifications)

    def test_alerts_include_expired_and_near(self):
        self.doc(-3)
        self.doc(20, kind=INSURANCE)
        self.doc(200, kind=document_kinds.MEDICAL)
        lefts = [left for _, left in reminders.alerts(self.profile, today=self.today)]
        self.assertEqual(lefts, [-3, 20])


class TelegramLinkTests(WizardFixture):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('pilot@example.com', 'pilot@example.com', 'pw')
        cfg = FeedbackBotSettings.get()
        cfg.is_enabled, cfg.bot_username = True, '@gripline_support_bot'
        cfg.save()

    def test_link_flow(self):
        url = telegram_link.start_link(self.user.profile)
        self.assertTrue(url.startswith('https://t.me/gripline_support_bot?start=link-'))
        param = url.split('start=')[1]
        self.assertLessEqual(len(param), 64)
        profile = telegram_link.complete_link(param, 555)
        self.assertEqual((profile.telegram_id, profile.telegram_notifications), (555, True))
        self.assertIsNone(telegram_link.complete_link(param, 555))   # одноразовый

    def test_expired_code_rejected(self):
        param = telegram_link.start_link(self.user.profile).split('start=')[1]
        self.user.profile.__class__.objects.filter(pk=self.user.profile.pk).update(
            telegram_link_created_at=timezone.now() - timedelta(hours=2))
        self.assertIsNone(telegram_link.complete_link(param, 555))

    def test_same_telegram_for_two_children(self):
        sibling = User.objects.create_user('kid2@example.com', 'kid2@example.com', 'pw')
        for user in (self.user, sibling):
            param = telegram_link.start_link(user.profile).split('start=')[1]
            self.assertIsNotNone(telegram_link.complete_link(param, 999))

    def test_connect_button_redirects_to_bot(self):
        self.client.force_login(self.user)
        resp = self.client.post('/accounts/telegram/connect/')
        self.assertTrue(resp['Location'].startswith('https://t.me/gripline_support_bot?start=link-'))



class NavbarBadgeTests(MediaMixin, WizardFixture):
    def test_counts_expired_and_near_documents(self):
        from accounts.templatetags.document_alert_tags import document_alert_count
        user = User.objects.create_user('pilot@example.com', 'pilot@example.com', 'pw')
        today = timezone.localdate()
        for days, kind in ((-1, LICENSE), (5, INSURANCE), (300, POA)):
            PilotDocument.objects.create(profile=user.profile, kind=kind, name=document_kinds.label(kind),
                                         file=pdf(), expiry_date=today + timedelta(days=days))
        self.assertEqual(document_alert_count(user), 2)
