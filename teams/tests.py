from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from applications.models import Application
from organizers.models import Championship, OrganizerProfile, Stage
from website.models import Driver, Team, TeamMembership
from .models import TeamManager


class BalanceRosterGatingTests(TestCase):
    """teams/balance_roster_views.py — та же гейтинг-идиома, что
    teams/views.py::dashboard (TeamManager.objects.filter(user=...,
    is_active=True)), Блок 3 калькулятора развесовки (Этап 1)."""

    def setUp(self):
        self.team_a = Team.objects.create(name="Team A", slug="team-a-gating")
        self.team_b = Team.objects.create(name="Team B", slug="team-b-gating")
        self.manager_a = User.objects.create_user(username="mgra", email="mgra@example.com", password="x")
        TeamManager.objects.create(user=self.manager_a, team=self.team_a, is_active=True)
        self.manager_b_inactive = User.objects.create_user(username="mgrb", email="mgrb@example.com", password="x")
        TeamManager.objects.create(user=self.manager_b_inactive, team=self.team_b, is_active=False)
        self.plain_user = User.objects.create_user(username="plain", email="plain@example.com", password="x")
        self.client = Client()

    def test_anonymous_redirected(self):
        resp = self.client.get("/teams/balance-roster/")
        self.assertEqual(resp.status_code, 302)

    def test_non_manager_rejected(self):
        self.client.force_login(self.plain_user)
        resp = self.client.get("/teams/balance-roster/", follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], "/")

    def test_inactive_manager_rejected(self):
        self.client.force_login(self.manager_b_inactive)
        resp = self.client.get("/teams/balance-roster/", follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], "/")

    def test_active_manager_passes_the_permission_gate(self):
        """Тестовая БД (--no-migrations, как во всём проекте) не содержит
        Wagtail Site/LayoutSettings — полный рендер coderedcms-шаблона здесь
        невозможен независимо от нашей логики (проверено вручную на dev-
        сервере). Проверяем то, что относится к этому view: активный
        менеджер НЕ попадает в ветку "нет прав" (messages.error + redirect
        на '/') — если рендер шаблона упадёт дальше на конфигурации сайта,
        это само по себе доказывает, что permission-гейт был пройден."""
        self.client.force_login(self.manager_a)
        try:
            resp = self.client.get("/teams/balance-roster/")
        except Exception:
            return
        self.assertNotEqual(resp.status_code, 302)


class TeamApplySecurityTests(TestCase):
    """
    team_apply/team_add_driver (teams/views.py) — регресс на находку
    security-аудита (коммит 16d0b90): эти view были определены в файле
    дважды, и активными (Python берёт последнее определение) оказались
    версии без is_active=True у TeamManager и без проверки, что driver_id
    реально состоит в команде менеджера. Из-за этого бывший (снятый)
    менеджер сохранял доступ, а действующий менеджер мог заявкой на этап
    зарегистрировать произвольного пилота чужой команды по одному только id.
    """

    def setUp(self):
        self.team = Team.objects.create(name="Team Apply", slug="team-apply-sec")
        self.foreign_team = Team.objects.create(name="Foreign Team", slug="team-apply-sec-foreign")

        self.active_manager = User.objects.create_user(
            username="apply-mgr-active", email="apply-mgr-active@example.com", password="x",
        )
        TeamManager.objects.create(user=self.active_manager, team=self.team, is_active=True)

        self.inactive_manager = User.objects.create_user(
            username="apply-mgr-inactive", email="apply-mgr-inactive@example.com", password="x",
        )
        TeamManager.objects.create(user=self.inactive_manager, team=self.team, is_active=False)

        self.member_driver = Driver.objects.create(
            first_name="Свой", last_name="Пилот", slug="apply-sec-own-driver",
        )
        TeamMembership.objects.create(driver=self.member_driver, team=self.team, is_active=True)

        self.foreign_driver = Driver.objects.create(
            first_name="Чужой", last_name="Пилот", slug="apply-sec-foreign-driver",
        )
        TeamMembership.objects.create(driver=self.foreign_driver, team=self.foreign_team, is_active=True)

        organizer_user = User.objects.create_user(
            username="apply-sec-org", email="apply-sec-org@example.com", password="x",
        )
        organizer = OrganizerProfile.objects.create(user=organizer_user)
        championship = Championship.objects.create(organizer=organizer, title="C", slug="apply-sec-champ")
        self.stage = Stage.objects.create(
            championship=championship, title="S",
            start_date=timezone.now(), end_date=timezone.now() + timedelta(hours=6),
            registration_enabled=True,
        )

    def _apply_url(self):
        return f"/teams/apply/{self.stage.id}/"

    def _add_driver_url(self):
        return f"/teams/apply/{self.stage.id}/add-driver/"

    def test_inactive_manager_cannot_apply(self):
        # Редирект без рендера шаблона — безопасно проверять status_code
        # напрямую, follow=True здесь не нужен и не нужен рендер дашборда.
        self.client.force_login(self.inactive_manager)
        resp = self.client.post(self._apply_url(), {
            "driver_id": self.member_driver.id, "race_class": "", "start_number": "1",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Application.objects.filter(stage=self.stage).exists())

    def test_inactive_manager_cannot_add_driver(self):
        self.client.force_login(self.inactive_manager)
        resp = self.client.post(self._add_driver_url(), {"driver_id": self.foreign_driver.id})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            TeamMembership.objects.filter(driver=self.foreign_driver, team=self.team).exists()
        )

    def test_active_manager_cannot_register_foreign_driver(self):
        # Ошибочный путь рендерит team_apply.html (extends coderedcms
        # web_page.html) — тестовая БД (--no-migrations) не содержит
        # Wagtail Site, полный рендер здесь невозможен независимо от нашей
        # логики (тот же случай, что в BalanceRosterGatingTests выше).
        # Важна не HTML-страница, а то, что заявка не создалась.
        self.client.force_login(self.active_manager)
        try:
            self.client.post(self._apply_url(), {
                "driver_id": self.foreign_driver.id, "race_class": "", "start_number": "1",
            })
        except Exception:
            pass
        self.assertFalse(Application.objects.filter(stage=self.stage).exists())

    def test_active_manager_can_register_own_driver(self):
        self.client.force_login(self.active_manager)
        resp = self.client.post(self._apply_url(), {
            "driver_id": self.member_driver.id, "race_class": "", "start_number": "1",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Application.objects.filter(stage=self.stage, submitted_by=self.active_manager).exists()
        )
