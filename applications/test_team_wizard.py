"""Заявка команды на этап: несколько пилотов, разные классы (applications/team_wizard.py)."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from organizers.models import Championship, OrganizerProfile, Stage
from teams.models import TeamManager
from website.models import Driver, RaceClass, Team, TeamMembership

from .models import Application, StageDocument, StageOption, TeamStageEntry

PILOT = {'last_name': '', 'first_name': '', 'middle_name': '', 'citizenship': 'Россия', 'birth_date': '1999-03-02',
         'sport_rank': '', 'license_number': '', 'email': '', 'phone': '+79990001122', 'city': 'Гатчина',
         'country': 'Россия'}
KART = {'kart-chassis_brand': 'Tony Kart', 'kart-engine_1': 'R1', 'kart-engine_2': '', 'kart-tires': '',
        'kart-transponder_number': '', 'kart-ad_consent': 'on'}
REP = {'rep_last_name': 'Петров', 'rep_first_name': 'Иван', 'rep_phone': '+7999', 'rep_email': 'mgr@example.com'}


class TeamWizardFixture(TestCase):
    def setUp(self):
        from django.conf import settings
        from wagtail.coreutils import get_supported_content_language_variant
        from wagtail.models import Locale, Page, Site
        Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
        Site.objects.create(hostname='testserver', root_page=Page.add_root(title='Root', slug='root'), is_default_site=True)
        org_user = User.objects.create_user('org', 'org@example.com', 'x')
        champ = Championship.objects.create(organizer=OrganizerProfile.objects.create(user=org_user, status='active'),
                                            title='Кубок', slug='kubok')
        self.mini, self.ok = RaceClass.objects.create(name='Мини'), RaceClass.objects.create(name='ОК')
        champ.race_classes.set([self.mini, self.ok])
        start = timezone.now() + timedelta(days=10)
        self.stage = Stage.objects.create(championship=champ, title='Этап 1', start_date=start,
                                          end_date=start + timedelta(hours=8), entry_fee=5000)
        StageDocument.objects.create(stage=self.stage, name='Медсправка')
        self.mandatory = StageOption.objects.create(stage=self.stage, name='Транспондер', price=500, is_mandatory=True)

        self.team = Team.objects.create(name='Альфа', slug='alfa')
        self.manager = User.objects.create_user('mgr', 'mgr@example.com', 'x', first_name='Иван', last_name='Петров')
        TeamManager.objects.create(user=self.manager, team=self.team, is_active=True)
        self.d1 = self._driver('Анна', 'Иванова', 'd1', race_class=self.mini)
        self.d2 = self._driver('Борис', 'Смирнов', 'd2', race_class=self.ok)
        self.d3 = self._driver('Вера', 'Кузнецова', 'd3')
        other = Team.objects.create(name='Бета', slug='beta')
        self.foreign = Driver.objects.create(first_name='Чужой', last_name='Пилот', slug='foreign', live=True)
        TeamMembership.objects.create(driver=self.foreign, team=other, is_active=True)
        self.client.force_login(self.manager)

    def _driver(self, first, last, slug, race_class=None):
        d = Driver.objects.create(first_name=first, last_name=last, slug=slug, live=True)
        TeamMembership.objects.create(driver=d, team=self.team, is_active=True, race_class=race_class)
        return d

    def entry(self):
        self.client.get(f'/teams/apply/{self.stage.id}/')
        return TeamStageEntry.objects.get(stage=self.stage, team=self.team)

    def roster(self, entry, rows, **extra):
        data = {**REP, **extra}
        for driver, cls, num in rows:
            key = f'd{driver.id}'
            data.update({f'pick_{key}': '1', f'class_{key}': cls.id if cls else '', f'part_{key}': 'race',
                         f'num_{key}': num or ''})
        return self.client.post(f'/teams/apply/entry/{entry.id}/', data)

    def fill(self, entry, app, **pilot):
        data = {**PILOT, 'last_name': app.pilot.last_name, 'first_name': app.pilot.first_name, **pilot, **KART}
        return self.client.post(f'/teams/apply/entry/{entry.id}/pilots/{app.id}/', data)


class TeamWizardRosterTests(TeamWizardFixture):
    def test_start_creates_one_entry_per_team_and_stage(self):
        resp = self.client.get(f'/teams/apply/{self.stage.id}/')
        entry = TeamStageEntry.objects.get()
        self.assertRedirects(resp, f'/teams/apply/entry/{entry.id}/', fetch_redirect_response=False)
        self.client.get(f'/teams/apply/{self.stage.id}/')
        self.assertEqual(TeamStageEntry.objects.count(), 1)
        self.assertEqual((entry.rep_last_name, entry.rep_email), ('Петров', 'mgr@example.com'))

    def test_roster_page_defaults_class_from_membership(self):
        resp = self.client.get(f'/teams/apply/entry/{self.entry().id}/')
        self.assertEqual(resp.status_code, 200)
        rows = {r.key: r for r in resp.context['rows']}
        self.assertEqual(rows[f'd{self.d1.id}'].class_id, self.mini.id)
        self.assertEqual(rows[f'd{self.d2.id}'].class_id, self.ok.id)
        self.assertNotIn(f'd{self.foreign.id}', rows)

    def test_pilots_in_different_classes_get_drafts_with_same_number(self):
        entry = self.entry()
        resp = self.roster(entry, [(self.d1, self.mini, 15), (self.d2, self.ok, 15)])
        self.assertRedirects(resp, f'/teams/apply/entry/{entry.id}/pilots/', fetch_redirect_response=False)
        apps = {a.pilot.driver_id: a for a in entry.applications.all()}
        self.assertEqual(set(apps), {self.d1.id, self.d2.id})
        a1 = apps[self.d1.id]
        self.assertEqual((a1.status, a1.submitted_by_type, a1.race_class, a1.start_number, a1.submitted_by),
                         ('draft', 'team', self.mini, 15, self.manager))
        self.assertEqual((a1.applicant.type, a1.applicant.team), ('team', self.team))
        self.assertEqual((a1.pilot.last_name, a1.pilot.first_name), ('Иванова', 'Анна'))
        entry.refresh_from_db()
        self.assertEqual(entry.rep_phone, '+7999')

    def test_same_number_twice_in_one_class_is_rejected(self):
        entry = self.entry()
        resp = self.roster(entry, [(self.d1, self.mini, 15), (self.d3, self.mini, 15)])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Application.objects.exists())
        errors = [e for r in resp.context['rows'] for e in r.errors]
        self.assertTrue(any('уже выбран' in e for e in errors))

    def test_number_taken_by_another_participant_is_rejected(self):
        Application.objects.create(stage=self.stage, submitted_by=User.objects.create_user('p', 'p@x.ru', 'x'),
                                   race_class=self.mini, start_number=15, status='submitted')
        entry = self.entry()
        resp = self.roster(entry, [(self.d1, self.mini, 15)])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(entry.applications.exists())

    def test_class_is_required_for_picked_pilot(self):
        entry = self.entry()
        resp = self.roster(entry, [(self.d3, None, None)])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(entry.applications.exists())

    def test_foreign_team_driver_cannot_be_injected_into_roster(self):
        entry = self.entry()
        key = f'd{self.foreign.id}'
        self.roster(entry, [(self.d1, self.mini, None)],
                    **{f'pick_{key}': '1', f'class_{key}': self.mini.id, f'part_{key}': 'race'})
        self.assertFalse(Application.objects.filter(pilot__driver=self.foreign).exists())

    def test_unpicking_pilot_deletes_his_draft(self):
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, None), (self.d2, self.ok, None)])
        self.roster(entry, [(self.d1, self.mini, None)])
        self.assertEqual(list(entry.applications.values_list('pilot__driver', flat=True)), [self.d1.id])

    def test_already_registered_pilot_is_rejected(self):
        own = Application.objects.create(stage=self.stage, submitted_by=User.objects.create_user('s', 's@x.ru', 'x'),
                                         race_class=self.mini, status='submitted')
        from .models import ApplicationPilot
        ApplicationPilot.objects.create(application=own, driver=self.d1, first_name='Анна', last_name='Иванова')
        entry = self.entry()
        resp = self.roster(entry, [(self.d1, self.mini, None)])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(entry.applications.exists())

    def test_capacity_limit(self):
        self.stage.max_participants = 1
        self.stage.save()
        entry = self.entry()
        resp = self.roster(entry, [(self.d1, self.mini, None), (self.d2, self.ok, None)])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(entry.applications.exists())

    def test_add_pilot_from_base_goes_to_entry_not_to_team(self):
        entry = self.entry()
        self.client.post(f'/teams/apply/entry/{entry.id}/add-pilot/', {'driver_id': self.foreign.id})
        app = entry.applications.get()
        self.assertEqual(app.pilot.driver, self.foreign)
        self.assertFalse(TeamMembership.objects.filter(team=self.team, driver=self.foreign).exists())

    def test_add_new_pilot_without_profile(self):
        entry = self.entry()
        self.client.post(f'/teams/apply/entry/{entry.id}/add-pilot/', {'last_name': 'Новый', 'first_name': 'Пилот'})
        app = entry.applications.get()
        self.assertEqual((app.pilot.driver, app.pilot.last_name), (None, 'Новый'))


class TeamWizardAccessTests(TeamWizardFixture):
    def test_old_add_driver_routes_are_gone(self):
        self.assertEqual(self.client.post('/teams/add-driver/', {'driver_id': self.foreign.id}).status_code, 404)
        self.assertEqual(self.client.post(f'/teams/apply/{self.stage.id}/add-driver/',
                                          {'driver_id': self.foreign.id}).status_code, 404)
        self.assertFalse(TeamMembership.objects.filter(team=self.team, driver=self.foreign).exists())

    def test_non_manager_and_inactive_manager_have_no_access(self):
        entry = self.entry()
        stranger = User.objects.create_user('x', 'x@x.ru', 'x')
        self.client.force_login(stranger)
        self.assertRedirects(self.client.get(f'/teams/apply/entry/{entry.id}/'), '/', fetch_redirect_response=False)
        self.roster(entry, [(self.d1, self.mini, None)])
        TeamManager.objects.filter(user=self.manager).update(is_active=False)
        self.client.force_login(self.manager)
        self.roster(entry, [(self.d1, self.mini, None)])
        self.assertFalse(entry.applications.exists())

    def test_manager_of_two_teams_chooses_team(self):
        second = Team.objects.create(name='Гамма', slug='gamma')
        TeamManager.objects.create(user=self.manager, team=second, is_active=True)
        resp = self.client.get(f'/teams/apply/{self.stage.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['teams']), 2)
        self.assertFalse(TeamStageEntry.objects.exists())
        self.client.get(f'/teams/apply/{self.stage.id}/?team={second.id}')
        self.assertEqual(TeamStageEntry.objects.get().team, second)

    def test_closed_registration(self):
        self.stage.registration_enabled = False
        self.stage.save()
        self.client.get(f'/teams/apply/{self.stage.id}/')
        self.assertFalse(TeamStageEntry.objects.exists())

    def test_team_drafts_do_not_leak_into_personal_wizard(self):
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, 15)])
        resp = self.client.get(f'/applications/apply/{self.stage.id}/')
        self.assertRedirects(resp, f'/applications/apply/{self.stage.id}/step/1/', fetch_redirect_response=False)
        # Менеджер сам едет в том же классе — командная заявка за другого пилота не дубль.
        from .views import _duplicate_application
        self.assertIsNone(_duplicate_application(self.stage, self.manager, 'pilot', self.mini.id))

    def test_detail_of_team_draft_redirects_to_team_wizard(self):
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, None)])
        app = entry.applications.get()
        self.assertRedirects(self.client.get(f'/applications/{app.id}/'),
                             f'/teams/apply/entry/{entry.id}/pilots/{app.id}/', fetch_redirect_response=False)


class TeamWizardSubmitTests(TeamWizardFixture):
    def test_pilot_card_marks_ready_and_next_pilot_gets_chassis(self):
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, None), (self.d2, self.ok, None)])
        a1, a2 = entry.applications.order_by('race_class__sort_order', 'pilot__last_name')
        self.fill(entry, a1, **{'mechanic-last_name': 'Механиков', 'mechanic-first_name': 'Пётр'})
        a1.refresh_from_db()
        self.assertEqual(a1.wizard_step, 2)
        resp = self.client.get(f'/teams/apply/entry/{entry.id}/pilots/{a2.id}/')
        self.assertEqual(resp.context['kart_form'].initial.get('chassis_brand'), 'Tony Kart')
        self.assertEqual(resp.context['mech_form'].initial.get('last_name'), 'Механиков')

    def test_minor_needs_parent(self):
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, None)])
        app = entry.applications.get()
        resp = self.fill(entry, app, birth_date=(timezone.now().date() - timedelta(days=365 * 12)).isoformat())
        self.assertEqual(resp.status_code, 200)
        app.refresh_from_db()
        self.assertEqual(app.wizard_step, 1)

    def test_submit_sends_ready_pilots_only_with_one_mail_each_side(self):
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, 15), (self.d2, self.ok, 22), (self.d3, self.mini, None)])
        ready = entry.applications.filter(pilot__driver__in=[self.d1, self.d2])
        for app in ready:
            self.fill(entry, app)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(f'/teams/apply/entry/{entry.id}/review/')
        self.assertRedirects(resp, f'/teams/apply/entry/{entry.id}/review/', fetch_redirect_response=False)
        statuses = dict(entry.applications.values_list('pilot__driver', 'status'))
        self.assertEqual(statuses, {self.d1.id: 'submitted', self.d2.id: 'submitted', self.d3.id: 'draft'})
        for app in entry.applications.filter(status='submitted'):
            self.assertEqual(app.documents.get().status, 'pending')
            self.assertEqual(app.get_total_amount(), 5500)          # обязательная опция добавлена
            self.assertEqual(app.payment.amount, 5500)
            self.assertEqual(app.applicant.rep_email, 'mgr@example.com')
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'submitted')
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['mgr@example.com', 'org@example.com'])
        page = self.client.get(f'/teams/apply/entry/{entry.id}/review/')
        self.assertEqual((page.status_code, page.context['ready_count']), (200, 0))
        self.assertEqual(self.client.get(f'/teams/apply/entry/{entry.id}/pilots/').status_code, 200)
        dashboard = self.client.get('/teams/dashboard/')
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context['stage_entries'][0]['total'], 3)

    def test_submit_without_ready_pilots(self):
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, None)])
        resp = self.client.post(f'/teams/apply/entry/{entry.id}/review/')
        self.assertRedirects(resp, f'/teams/apply/entry/{entry.id}/pilots/', fetch_redirect_response=False)
        self.assertEqual(entry.applications.get().status, 'draft')

    def test_submitted_pilot_is_locked_in_roster(self):
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, 15)])
        app = entry.applications.get()
        self.fill(entry, app)
        self.client.post(f'/teams/apply/entry/{entry.id}/review/')
        # Повторное сохранение состава без d1 не удаляет отправленную заявку.
        self.roster(entry, [(self.d2, self.ok, None)])
        app.refresh_from_db()
        self.assertEqual(app.status, 'submitted')
        self.assertEqual(entry.applications.count(), 2)

    def test_personal_data_carried_from_previous_team_entry(self):
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, None)])
        self.fill(entry, entry.applications.get(), license_number='LIC-7')
        self.client.post(f'/teams/apply/entry/{entry.id}/review/')
        start = timezone.now() + timedelta(days=40)
        stage2 = Stage.objects.create(championship=self.stage.championship, title='Этап 2', start_date=start,
                                      end_date=start + timedelta(hours=8), entry_fee=5000)
        self.client.get(f'/teams/apply/{stage2.id}/')
        entry2 = TeamStageEntry.objects.get(stage=stage2)
        self.roster(entry2, [(self.d1, self.mini, None)])
        self.assertEqual(entry2.applications.get().pilot.license_number, 'LIC-7')


class TeamWizardStage2Tests(TeamWizardFixture):
    """Этап 2: документы из ЛК пилота (членство в команде = согласие), общий доступ менеджеров,
    опции по пилотам, оплата одной квитанцией."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from django.test import override_settings
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        import shutil
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        from . import document_kinds
        self.license = StageDocument.objects.create(stage=self.stage, kind=document_kinds.LICENSE)
        self.pilot_user = User.objects.create_user('anna@example.com', 'anna@example.com', 'x')
        profile = self.pilot_user.profile
        profile.driver, profile.verified = self.d1, True
        profile.save()
        self.profile = profile

    def pdf(self, name='scan.pdf'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, b'%PDF-1.4 test', content_type='application/pdf')

    def vault_license(self):
        from accounts.models import PilotDocument
        return PilotDocument.objects.create(profile=self.profile, kind='license', name='Лицензия', file=self.pdf(),
                                            expiry_date=self.stage.end_date.date() + timedelta(days=90))

    def sent(self, *drivers):
        entry = self.entry()
        classes = {self.d1.id: self.mini, self.d2.id: self.ok, self.d3.id: self.mini}
        self.roster(entry, [(d, classes.get(d.id, self.mini), None) for d in drivers])
        for app in entry.applications.all():
            self.fill(entry, app)
        self.client.post(f'/teams/apply/entry/{entry.id}/review/', {'action': 'submit'})
        return entry

    def test_roster_pilot_documents_come_from_his_cabinet(self):
        saved = self.vault_license()
        entry = self.sent(self.d1)
        row = entry.applications.get().documents.get(stage_document=self.license)
        self.assertEqual((row.status, row.vault_document), ('uploaded', saved))

    def test_pilot_added_outside_roster_gets_nothing_from_cabinet(self):
        self.vault_license()
        TeamMembership.objects.filter(driver=self.d1, team=self.team).update(is_active=False)
        entry = self.entry()
        self.client.post(f'/teams/apply/entry/{entry.id}/add-pilot/', {'driver_id': self.d1.id})
        app = entry.applications.get()
        self.client.post(f'/teams/apply/entry/{entry.id}/', {
            **REP, f'pick_a{app.id}': '1', f'class_a{app.id}': self.mini.id, f'part_a{app.id}': 'race'})
        self.fill(entry, app)
        self.client.post(f'/teams/apply/entry/{entry.id}/review/', {'action': 'submit'})
        self.assertEqual(app.documents.get(stage_document=self.license).status, 'pending')

    def test_manager_upload_lands_in_pilot_cabinet_and_returns_to_team_page(self):
        from accounts.models import PilotDocument
        entry = self.sent(self.d1)
        row = entry.applications.get().documents.get(stage_document=self.license)
        back = f'/teams/apply/entry/{entry.id}/review/'
        resp = self.client.post(f'/applications/document/{row.id}/upload/', {
            'file': self.pdf(), 'expiry_date': '2030-01-01', 'next': back})
        self.assertRedirects(resp, back, fetch_redirect_response=False)
        doc = PilotDocument.objects.get(profile=self.profile, kind='license')
        self.assertEqual(str(doc.expiry_date), '2030-01-01')

    def test_upload_next_must_be_local(self):
        entry = self.sent(self.d1)
        row = entry.applications.get().documents.get(stage_document=self.license)
        resp = self.client.post(f'/applications/document/{row.id}/upload/', {
            'file': self.pdf(), 'expiry_date': '2030-01-01', 'next': 'https://evil.example/'})
        self.assertRedirects(resp, f'/applications/{row.application_id}/', fetch_redirect_response=False)

    def test_second_manager_of_team_sees_and_uploads(self):
        entry = self.sent(self.d2)
        app = entry.applications.get()
        other = User.objects.create_user('mgr2', 'mgr2@example.com', 'x')
        TeamManager.objects.create(user=other, team=self.team, is_active=True)
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'/applications/{app.id}/').status_code, 200)
        self.assertEqual(self.client.get(f'/teams/apply/entry/{entry.id}/review/').status_code, 200)
        stranger = User.objects.create_user('st', 'st@example.com', 'x')
        self.client.force_login(stranger)
        self.assertRedirects(self.client.get(f'/applications/{app.id}/'), '/', fetch_redirect_response=False)

    def test_options_per_pilot(self):
        extra = StageOption.objects.create(stage=self.stage, name='Слики', price=1000)
        entry = self.entry()
        self.roster(entry, [(self.d1, self.mini, None), (self.d2, self.ok, None)])
        a1 = entry.applications.get(pilot__driver=self.d1)
        self.client.post(f'/teams/apply/entry/{entry.id}/review/', {'action': 'options', f'opt_{a1.id}_{extra.id}': '1'})
        self.assertEqual(a1.get_total_amount(), 6500)            # 5000 + обязательная 500 + слики
        a2 = entry.applications.get(pilot__driver=self.d2)
        self.assertEqual(a2.get_total_amount(), 5500)

    def test_single_receipt_attached_to_waiting_payments(self):
        entry = self.sent(self.d1, self.d2)
        verified = entry.applications.get(pilot__driver=self.d2).payment
        verified.status = 'verified'
        verified.save()
        url = f'/teams/apply/entry/{entry.id}/review/'
        self.client.post(url, {'action': 'payment_mode', 'payment_mode': 'single'})
        self.client.post(url, {'action': 'receipt', 'receipt': self.pdf('pay.pdf')})
        entry.refresh_from_db()
        p1 = entry.applications.get(pilot__driver=self.d1).payment
        self.assertEqual((p1.status, p1.receipt_file.name), ('uploaded', entry.receipt_file.name))
        verified.refresh_from_db()
        self.assertEqual((verified.status, bool(verified.receipt_file)), ('verified', False))
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)

    def test_documents_of_pilot_without_confirmed_account_are_held_and_move_to_cabinet(self):
        from accounts.models import DriverClaim, PilotDocument
        entry = self.sent(self.d2)                                   # у d2 нет подтверждённого аккаунта
        row = entry.applications.get().documents.get(stage_document=self.license)
        self.client.post(f'/applications/document/{row.id}/upload/', {'file': self.pdf(), 'expiry_date': '2030-01-01'})
        held = PilotDocument.objects.get(driver=self.d2)
        self.assertIsNone(held.profile)

        # Следующий этап: документ подставляется из хранилища пилота.
        start = timezone.now() + timedelta(days=40)
        stage2 = Stage.objects.create(championship=self.stage.championship, title='Этап 2', start_date=start,
                                      end_date=start + timedelta(hours=8), entry_fee=5000)
        from . import document_kinds
        lic2 = StageDocument.objects.create(stage=stage2, kind=document_kinds.LICENSE)
        self.client.get(f'/teams/apply/{stage2.id}/')
        entry2 = TeamStageEntry.objects.get(stage=stage2)
        self.roster(entry2, [(self.d2, self.ok, None)])
        app2 = entry2.applications.get()
        self.fill(entry2, app2)
        self.client.post(f'/teams/apply/entry/{entry2.id}/review/', {'action': 'submit'})
        self.assertEqual(app2.documents.get(stage_document=lic2).vault_document, held)

        # Неподтверждённый аккаунт, назвавшийся этим пилотом, документа не видит.
        boris = User.objects.create_user('boris@example.com', 'boris@example.com', 'x')
        claim = DriverClaim.objects.create(user=boris, driver=self.d2, status='pending')
        boris.profile.refresh_from_db()
        self.assertFalse(boris.profile.documents.exists())
        # Подтвердили — документ в его ЛК.
        claim.status = 'approved'
        claim.save()
        held.refresh_from_db()
        self.assertEqual(held.profile, boris.profile)

    def test_held_document_older_than_cabinet_one_is_dropped_on_attach(self):
        from accounts.models import PilotDocument
        from .vault import attach_held_documents
        old = PilotDocument.objects.create(driver=self.d1, kind='license', name='Лицензия', file=self.pdf())
        newer = self.vault_license()                 # уже в ЛК d1, загружен позже
        attach_held_documents(self.profile)
        self.assertFalse(PilotDocument.objects.filter(pk=old.pk).exists())
        self.assertTrue(PilotDocument.objects.filter(pk=newer.pk, profile=self.profile).exists())
