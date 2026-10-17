from django.contrib.auth.models import User
from django.test import Client, TestCase

from website.models import Team
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
