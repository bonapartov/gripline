"""Мастер подачи заявки на этап (applications/wizard.py)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from accounts.models import DriverClaim
from organizers.models import Championship, OrganizerProfile, Stage
from teams.models import TeamClaim
from website.models import Driver, RaceClass, Team

from .models import Application, StageDocument, StageOption

PILOT = {
    'last_name': 'Новиков', 'first_name': 'Пётр', 'middle_name': '', 'citizenship': 'Россия', 'birth_date': '2000-05-01',
    'sport_rank': '', 'license_number': '', 'email': '', 'phone': '+79990001122', 'city': 'Гатчина', 'country': 'Россия',
}
KART = {'kart-chassis_brand': 'Tony Kart', 'kart-engine_1': 'R123', 'kart-engine_2': '', 'kart-tires': '',
        'kart-transponder_number': '', 'kart-ad_consent': 'on'}


class WizardFixture(TestCase):
    def setUp(self):
        from django.conf import settings
        from wagtail.coreutils import get_supported_content_language_variant
        from wagtail.models import Locale, Page, Site
        Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
        Site.objects.create(hostname='testserver', root_page=Page.add_root(title='Root', slug='root'), is_default_site=True)
        org_user = User.objects.create_user('org', 'org@example.com', 'x')
        self.organizer = OrganizerProfile.objects.create(user=org_user, status='active')
        champ = Championship.objects.create(organizer=self.organizer, title='Кубок', slug='kubok')
        self.mini = RaceClass.objects.create(name='Мини')
        champ.race_classes.set([self.mini])
        start = timezone.now() + timedelta(days=10)
        self.stage = Stage.objects.create(championship=champ, title='Этап 1', start_date=start,
                                          end_date=start + timedelta(hours=8), entry_fee=5000)
        StageDocument.objects.create(stage=self.stage, name='Медсправка')
        self.option = StageOption.objects.create(stage=self.stage, name='Транспондер', price=500)

    def url(self, step):
        return f'/applications/apply/{self.stage.id}/step/{step}/'

    def step1(self, number=15):
        return self.client.post(self.url(1), {'participation': 'race', 'race_class': self.mini.id, 'start_number': number})

    def step3(self, **extra):
        data = {**KART, 'applicant-type': 'individual', 'applicant-name': 'Новиков Пётр', **extra}
        return self.client.post(self.url(3), data)

    def finish(self):
        self.client.post(self.url(4), {f'option_{self.option.id}': '1'})
        return self.client.post(self.url(5))


@mock.patch('website.claim_notify._deliver')
class GuestWizardTests(WizardFixture):
    def test_guest_full_path_creates_account_application_and_pilot_claim(self, deliver):
        self.assertEqual(self.step1().status_code, 302)
        self.assertFalse(Application.objects.exists())   # гость: шаг ① в сессии
        resp = self.client.post(self.url(2), {**PILOT, 'email_account': 'new@example.com', 'guest_mode': 'new'})
        self.assertRedirects(resp, self.url(3), fetch_redirect_response=False)
        user = User.objects.get(email='new@example.com')
        self.assertTrue(user.has_usable_password())           # иначе Django не пришлёт письмо сброса
        app = Application.objects.get()
        self.assertEqual((app.status, app.start_number, app.submitted_by), ('draft', 15, user))
        self.assertFalse(DriverClaim.objects.exists())          # заявка на профиль — только при отправке
        self.step3()
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.finish()
        app.refresh_from_db()
        self.assertRedirects(resp, f'/applications/{app.id}/', fetch_redirect_response=False)
        self.assertEqual(app.status, 'submitted')
        self.assertEqual(app.get_total_amount(), 5500)
        self.assertEqual(app.documents.get().status, 'pending')      # документы — догрузить позже
        claim = DriverClaim.objects.get(user=user)
        self.assertEqual((claim.status, claim.driver), ('pending', None))
        self.assertEqual(app.pilot.driver_claim, claim)
        deliver.assert_called()                                      # админу — письмо + Telegram
        recipients = [m.to[0] for m in mail.outbox]
        self.assertIn('org@example.com', recipients)                 # организатору — новая заявка
        self.assertIn('new@example.com', recipients)                 # участнику — заявка отправлена

        claim.status = 'approved'
        claim.save()
        app.pilot.refresh_from_db()
        self.assertIsNotNone(app.pilot.driver)                       # одобрили — заявка привязана к пилоту
        self.assertEqual(app.pilot.driver.last_name, 'Новиков')

    def test_taken_email_asks_to_log_in_and_keeps_step_one(self, deliver):
        old = User.objects.create_user('old@example.com', 'old@example.com', 'pw')
        self.step1(number=21)
        resp = self.client.post(self.url(2), {**PILOT, 'email_account': 'old@example.com', 'guest_mode': 'new'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'уже зарегистрирован')
        self.assertFalse(Application.objects.exists())
        self.client.force_login(old)
        resp = self.client.post(self.url(2), PILOT)            # вошёл — шаг ① из сессии сохранился
        self.assertRedirects(resp, self.url(3), fetch_redirect_response=False)
        self.assertEqual(Application.objects.get().start_number, 21)

    def test_cannot_skip_steps(self, deliver):
        resp = self.client.get(self.url(3))
        self.assertRedirects(resp, self.url(1), fetch_redirect_response=False)

    def test_all_missing_required_fields_marked_invalid(self, deliver):
        self.step1()
        resp = self.client.post(self.url(2), {'guest_mode': 'new'})
        html = resp.content.decode()
        for field in ('id_last_name', 'id_first_name', 'id_email_account'):
            self.assertRegex(html, rf'class="[^"]*is-invalid[^"]*"[^>]*id="{field}"|id="{field}"[^>]*class="[^"]*is-invalid')


@mock.patch('website.claim_notify._deliver')
class LoggedInWizardTests(WizardFixture):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('pilot@example.com', 'pilot@example.com', 'pw')
        self.client.force_login(self.user)

    def test_existing_driver_choice_creates_claim_on_that_driver(self, deliver):
        driver = Driver.objects.create(first_name='Пётр', last_name='Новиков', slug='novikov')
        self.step1()
        resp = self.client.post(self.url(2), PILOT)       # совпало имя — спрашиваем «это вы?»
        self.assertContains(resp, 'Это вы?')
        self.client.post(self.url(2), {**PILOT, 'driver_choice': str(driver.id)})
        self.step3()
        self.finish()
        self.assertEqual(DriverClaim.objects.get(user=self.user).driver, driver)

    def test_new_team_creates_team_claim_for_contact_and_links_on_approval(self, deliver):
        self.step1()
        self.client.post(self.url(2), PILOT)
        resp = self.step3(**{'applicant-type': 'team', 'applicant-team_mode': 'new',
                             'applicant-new_team_name': 'Kart Lab', 'applicant-new_team_city': 'Гатчина',
                             'applicant-new_team_email': 'boss@example.com'})
        self.assertRedirects(resp, self.url(4), fetch_redirect_response=False)
        self.finish()
        claim = TeamClaim.objects.get()
        self.assertEqual((claim.user.email, claim.requested_team_name, claim.status),
                         ('boss@example.com', 'Kart Lab', 'pending'))
        claim.status = 'approved'
        claim.save()
        app = Application.objects.get()
        self.assertEqual(app.applicant.team.name, 'Kart Lab')
        self.assertTrue(claim.user.team_managers.filter(team__name='Kart Lab', is_active=True).exists())

    def test_team_from_list(self, deliver):
        team = Team.objects.create(name='Speed')
        self.step1()
        self.client.post(self.url(2), PILOT)
        self.step3(**{'applicant-type': 'team', 'applicant-team_mode': 'existing', 'applicant-team': team.id})
        self.finish()
        app = Application.objects.get()
        self.assertEqual((app.applicant.team, app.applicant.name), (team, 'Speed'))
        self.assertFalse(TeamClaim.objects.exists())

    def test_every_step_renders(self, deliver):
        self.step1()
        self.client.post(self.url(2), PILOT)
        self.step3()
        self.client.post(self.url(4), {})
        for step in range(1, 6):
            resp = self.client.get(self.url(step))
            self.assertEqual(resp.status_code, 200, step)
            self.assertContains(resp, 'wz-step current')
        resp = self.client.get(self.url(5))
        self.assertContains(resp, 'Медсправка')          # предупреждение о документах на шаге ⑤

    def test_draft_resumes_from_next_step(self, deliver):
        self.step1()
        resp = self.client.get(f'/applications/apply/{self.stage.id}/')
        self.assertRedirects(resp, self.url(2), fetch_redirect_response=False)

    def test_withdraw_frees_number_and_notifies_organizer(self, deliver):
        self.step1(number=33)
        self.client.post(self.url(2), PILOT)
        self.step3()
        self.finish()
        app = Application.objects.get()
        mail.outbox.clear()
        self.assertEqual(self.client.get(f'/applications/{app.id}/cancel/').status_code, 302)   # GET ничего не делает
        app.refresh_from_db()
        self.assertEqual(app.status, 'submitted')
        self.client.post(f'/applications/{app.id}/cancel/', {'reason': 'Сломался карт'})
        app.refresh_from_db()
        self.assertEqual((app.status, app.withdraw_reason), ('cancelled', 'Сломался карт'))
        self.assertIn(33, self.stage.get_available_numbers(race_class=self.mini))
        self.assertEqual(mail.outbox[0].to, ['org@example.com'])
        self.assertIn('отозвана', mail.outbox[0].subject)

    def test_cannot_withdraw_after_stage_start(self, deliver):
        app = Application.objects.create(stage=self.stage, submitted_by=self.user, status='confirmed')
        Stage.objects.filter(pk=self.stage.pk).update(start_date=timezone.now() - timedelta(hours=1))
        self.client.post(f'/applications/{app.id}/cancel/')
        app.refresh_from_db()
        self.assertEqual(app.status, 'confirmed')


class PasswordResetVerifiesEmailTests(WizardFixture):
    def test_reset_confirm_marks_email_verified(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        from accounts.verification import is_email_verified, mark_unverified
        user = User.objects.create_user('n@example.com', 'n@example.com', 'random-unknown')
        mark_unverified(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        resp = self.client.get(f'/accounts/password-reset/{uid}/{token}/', follow=True)
        url = resp.redirect_chain[-1][0]
        self.client.post(url, {'new_password1': 'Very-strong-pass-42', 'new_password2': 'Very-strong-pass-42'})
        user.refresh_from_db()
        self.assertTrue(is_email_verified(user))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)   # автовход после сброса
        self.assertTrue(user.check_password('Very-strong-pass-42'))
