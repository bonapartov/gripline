"""
Тесты прав доступа и сохранения сетапов развесовки — Блок 3 ТЗ «Сервис
расчёта развесовки карта», Этап 1 (см. /home/v/.claude/plans/smooth-snacking-spindle.md).

Покрывает website/services/balance_permissions.py (изоляция видимости
между несвязанными пользователями/командами, права на редактирование) и
website/balance_setup_views.py::kart_create/kart_archive (Этап 1 — только
пилотский Kart CRUD; Setup CRUD и teams/balance_roster_views.py тестируются
следующими этапами того же плана).
"""
import json
import re

from django.contrib.auth.models import User
from django.test import Client, TestCase

from teams.models import TeamManager
from website.models import (
    Ballast,
    Chassis,
    ChassisTypePreset,
    Driver,
    Kart,
    KartClass,
    Setup,
    Team,
    TeamMembership,
    TeamRosterEntry,
)
from website.services.balance_permissions import (
    can_edit_kart,
    can_edit_setup,
    get_balance_identity,
    visible_karts_for_user,
    visible_setups_for_user,
)


def _make_driver_user(username, verified=True):
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x")
    driver = Driver.objects.create(first_name="Пилот", last_name=username, slug=f"{username}-driver")
    profile = user.profile
    profile.driver = driver
    profile.verified = verified
    profile.save()
    return user, driver


def _make_manager_user(username, team):
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x")
    TeamManager.objects.create(user=user, team=team, is_active=True)
    return user


class BalanceTestData:
    """Общие фикстуры — не unittest, просто фабрика, чтобы не дублировать
    setUp построчно в каждом TestCase."""

    @staticmethod
    def build():
        ChassisTypePreset.objects.create(
            chassis_type="junior", wheelbase_mm=1000, track_front_mm=800, track_rear_mm=850,
        )
        chassis = Chassis.objects.create(name="TestChassis")
        kart_class = KartClass.objects.create(
            name="Junior Test", slug="junior-test", chassis_type="junior", min_weight_kg=100,
        )
        return chassis, kart_class


class VisibilityIsolationTests(TestCase):
    """website/services/balance_permissions.py — видит только своё/расшаренное."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()

        self.team_a = Team.objects.create(name="Team A", slug="team-a")
        self.team_b = Team.objects.create(name="Team B", slug="team-b")

        self.driver_x_user, self.driver_x = _make_driver_user("driverx")
        self.driver_y_user, self.driver_y = _make_driver_user("drivery")

        self.manager_a_user = _make_manager_user("managera", self.team_a)
        self.manager_b_user = _make_manager_user("managerb", self.team_b)

        self.kart_x = Kart.objects.create(
            name="Kart X", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver_x,
        )
        self.kart_team_a = Kart.objects.create(
            name="Kart A", chassis=self.chassis, chassis_type="junior", owner_team=self.team_a,
        )

    def _setup_for(self, kart, **overrides):
        defaults = dict(
            kart=kart, name="Setup", kart_class=self.kart_class,
            weight_lf=25, weight_rf=25, weight_lr=25, weight_rr=25,
        )
        defaults.update(overrides)
        return Setup.objects.create(**defaults)

    def test_driver_sees_only_own_kart_by_default(self):
        self.assertIn(self.kart_x, visible_karts_for_user(self.driver_x_user))
        self.assertNotIn(self.kart_team_a, visible_karts_for_user(self.driver_x_user))

    def test_unrelated_driver_sees_nothing_of_another_drivers_setup(self):
        setup = self._setup_for(self.kart_x)
        self.assertNotIn(setup, visible_setups_for_user(self.driver_y_user))
        self.assertFalse(can_edit_setup(self.driver_y_user, setup))

    def test_manager_of_team_b_sees_nothing_of_team_a(self):
        setup = self._setup_for(self.kart_team_a)
        self.assertNotIn(self.kart_team_a, visible_karts_for_user(self.manager_b_user))
        self.assertNotIn(setup, visible_setups_for_user(self.manager_b_user))

    def test_manager_of_team_a_sees_all_team_a_setups_without_share_flag(self):
        setup = self._setup_for(self.kart_team_a)  # shared_with_* всё ещё False
        self.assertIn(setup, visible_setups_for_user(self.manager_a_user))
        self.assertTrue(can_edit_setup(self.manager_a_user, setup))

    def test_shared_with_driver_resolves_via_roster_entry_specifically(self):
        roster_entry = TeamRosterEntry.objects.create(
            team=self.team_a, last_name="Иванов", first_name="Пётр", driver=self.driver_x,
        )
        self.kart_team_a.roster_entry = roster_entry
        self.kart_team_a.save()
        setup = self._setup_for(self.kart_team_a, shared_with_driver=True)

        self.assertIn(setup, visible_setups_for_user(self.driver_x_user))
        # driver_y НЕ закреплён в ростере этого карта — не должен видеть,
        # даже если бы карт был расшарен пилоту вообще
        self.assertNotIn(setup, visible_setups_for_user(self.driver_y_user))

    def test_shared_with_team_survives_membership_leaving(self):
        """ТЗ §4.6: уход пилота из команды НЕ отзывает доступ команды к уже
        расшаренным сетапам — 'автоматического отзыва нет'."""
        TeamMembership.objects.create(driver=self.driver_x, team=self.team_a, is_active=False)
        setup = self._setup_for(self.kart_x, shared_with_team=True)

        self.assertIn(setup, visible_setups_for_user(self.manager_a_user))

    def test_not_shared_setup_invisible_to_team(self):
        TeamMembership.objects.create(driver=self.driver_x, team=self.team_a, is_active=True)
        setup = self._setup_for(self.kart_x, shared_with_team=False)

        self.assertNotIn(setup, visible_setups_for_user(self.manager_a_user))

    def test_can_edit_kart_owner_vs_others(self):
        self.assertTrue(can_edit_kart(self.driver_x_user, self.kart_x))
        self.assertFalse(can_edit_kart(self.driver_y_user, self.kart_x))
        self.assertTrue(can_edit_kart(self.manager_a_user, self.kart_team_a))
        self.assertFalse(can_edit_kart(self.manager_b_user, self.kart_team_a))

    def test_unverified_driver_profile_has_no_identity(self):
        unverified_user, _ = _make_driver_user("unverified", verified=False)
        identity = get_balance_identity(unverified_user)
        self.assertIsNone(identity["driver"])
        self.assertFalse(identity["managed_teams"].exists())

    def test_organizer_only_user_has_no_access(self):
        organizer_user = User.objects.create_user(username="organizer1", email="o1@example.com", password="x")
        identity = get_balance_identity(organizer_user)
        self.assertIsNone(identity["driver"])
        self.assertFalse(identity["managed_teams"].exists())
        self.assertFalse(visible_karts_for_user(organizer_user).exists())

    def test_archived_kart_excluded_by_default_included_when_requested(self):
        self.kart_x.is_archived = True
        self.kart_x.save()
        self.assertNotIn(self.kart_x, visible_karts_for_user(self.driver_x_user))
        self.assertIn(self.kart_x, visible_karts_for_user(self.driver_x_user, include_archived=True))


class KartCreateArchiveViewTests(TestCase):
    """website/balance_setup_views.py — эндпоинты Этапа 1."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()
        self.driver_user, self.driver = _make_driver_user("pilot1")
        self.other_user, self.other_driver = _make_driver_user("pilot2")
        self.client = Client()

    def test_kart_create_requires_login(self):
        resp = self.client.post("/balance/kart/create/", data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 302)  # редирект на логин

    def test_kart_create_requires_verified_driver(self):
        anon_user = User.objects.create_user(username="noident", email="ni@example.com", password="x")
        self.client.force_login(anon_user)
        resp = self.client.post(
            "/balance/kart/create/",
            data=json.dumps({"name": "K1", "chassis_id": self.chassis.id, "chassis_type": "junior"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_kart_create_success(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/kart/create/",
            data=json.dumps({"name": "Мой карт", "chassis_id": self.chassis.id, "chassis_type": "junior"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        kart = Kart.objects.get(name="Мой карт")
        self.assertEqual(kart.owner_driver_id, self.driver.id)

    def test_kart_create_rejects_missing_chassis(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/kart/create/",
            data=json.dumps({"name": "Карт без шасси", "chassis_type": "junior"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Kart.objects.filter(name="Карт без шасси").exists())

    def test_kart_create_enforces_cap(self):
        from website import balance_setup_views
        # balance_setup_views импортирует MAX_KARTS_PER_OWNER по имени
        # (`from ... import MAX_KARTS_PER_OWNER`) — патчить нужно именно
        # это связывание в модуле view, не атрибут исходного модуля.
        original = balance_setup_views.MAX_KARTS_PER_OWNER
        balance_setup_views.MAX_KARTS_PER_OWNER = 1
        try:
            Kart.objects.create(
                name="Existing", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
            )
            self.client.force_login(self.driver_user)
            resp = self.client.post(
                "/balance/kart/create/",
                data=json.dumps({"name": "Second", "chassis_id": self.chassis.id, "chassis_type": "junior"}),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 400)
        finally:
            balance_setup_views.MAX_KARTS_PER_OWNER = original

    def test_kart_archive_owner_only_others_get_404_not_403(self):
        kart = Kart.objects.create(
            name="K", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
        )
        self.client.force_login(self.other_user)
        resp = self.client.post(
            f"/balance/kart/{kart.id}/archive/",
            data=json.dumps({"archived": True}),
            content_type="application/json",
        )
        # Не 403 — чужой карт не должен палить своё существование ответом,
        # отличимым от несуществующего id.
        self.assertEqual(resp.status_code, 404)
        kart.refresh_from_db()
        self.assertFalse(kart.is_archived)

    def test_kart_archive_owner_can_toggle(self):
        kart = Kart.objects.create(
            name="K", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
        )
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            f"/balance/kart/{kart.id}/archive/",
            data=json.dumps({"archived": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        kart.refresh_from_db()
        self.assertTrue(kart.is_archived)
        # мягкое архивирование — запись остаётся в БД, не удаляется
        self.assertTrue(Kart.objects.filter(pk=kart.pk).exists())


class SetupSaveViewTests(TestCase):
    """website/balance_setup_views.py::setup_save — Этап 2 (только создание)."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()
        self.driver_user, self.driver = _make_driver_user("setuppilot")
        self.other_user, self.other_driver = _make_driver_user("otherpilot")
        self.kart = Kart.objects.create(
            name="Мой карт", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
        )
        self.client = Client()

    def _payload(self, **overrides):
        payload = {
            "kart_id": self.kart.id,
            "name": "Мячково, сухо",
            "class_id": self.kart_class.id,
            "corners": {"lf": "30.0", "rf": "31.0", "lr": "29.0", "rr": "30.0"},
        }
        payload.update(overrides)
        return payload

    def test_requires_login(self):
        resp = self.client.post(
            "/balance/setup/save/", data=json.dumps(self._payload()), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 302)

    def test_foreign_kart_returns_404_not_403(self):
        self.client.force_login(self.other_user)
        resp = self.client.post(
            "/balance/setup/save/", data=json.dumps(self._payload()), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(Setup.objects.filter(kart=self.kart).exists())

    def test_missing_class_rejected(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/",
            data=json.dumps(self._payload(class_id=None)),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_incomplete_corners_rejected(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/",
            data=json.dumps(self._payload(corners={"lf": "30.0", "rf": "", "lr": "29.0", "rr": "30.0"})),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Setup.objects.filter(kart=self.kart).exists())

    def test_chassis_type_mismatch_rejected(self):
        senior_class = KartClass.objects.create(
            name="Senior Test", slug="senior-test", chassis_type="senior", min_weight_kg=150,
        )
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/",
            data=json.dumps(self._payload(class_id=senior_class.id)),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_success_creates_setup_with_default_name_and_ballasts(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/",
            data=json.dumps(self._payload(
                name="",
                ballasts=[{"weight_kg": "2.0", "pos_x_mm": "100.0", "pos_y_mm": "200.0", "label": "под сиденьем"}],
            )),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        setup = Setup.objects.get(kart=self.kart)
        self.assertTrue(setup.name)  # дефолтное имя подставлено, не пусто
        self.assertEqual(setup.kart_class_id, self.kart_class.id)
        self.assertEqual(Ballast.objects.filter(setup=setup).count(), 1)

    def test_driver_weight_defaults_from_last_setup_on_same_kart(self):
        Setup.objects.create(
            kart=self.kart, name="Прошлый", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30, driver_weight_kg="55.5",
        )
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/", data=json.dumps(self._payload()), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        new_setup = Setup.objects.exclude(name="Прошлый").get(kart=self.kart)
        self.assertEqual(str(new_setup.driver_weight_kg), "55.5")

    def test_max_setups_per_kart_enforced(self):
        from website import balance_setup_views
        original = balance_setup_views.MAX_SETUPS_PER_KART
        balance_setup_views.MAX_SETUPS_PER_KART = 1
        try:
            Setup.objects.create(
                kart=self.kart, name="Существующий", kart_class=self.kart_class,
                weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30,
            )
            self.client.force_login(self.driver_user)
            resp = self.client.post(
                "/balance/setup/save/", data=json.dumps(self._payload()), content_type="application/json",
            )
            self.assertEqual(resp.status_code, 400)
        finally:
            balance_setup_views.MAX_SETUPS_PER_KART = original

    def test_max_ballasts_per_setup_enforced(self):
        from website import balance_setup_views
        original = balance_setup_views.MAX_BALLASTS_PER_SETUP
        balance_setup_views.MAX_BALLASTS_PER_SETUP = 1
        try:
            self.client.force_login(self.driver_user)
            resp = self.client.post(
                "/balance/setup/save/",
                data=json.dumps(self._payload(ballasts=[
                    {"weight_kg": "1", "pos_x_mm": "1", "pos_y_mm": "1"},
                    {"weight_kg": "2", "pos_x_mm": "2", "pos_y_mm": "2"},
                ])),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 400)
        finally:
            balance_setup_views.MAX_BALLASTS_PER_SETUP = original

class SetupUpdateViewTests(TestCase):
    """website/balance_setup_views.py::setup_save — update-путь (Этап 4)."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()
        self.driver_user, self.driver = _make_driver_user("editpilot")
        self.other_user, self.other_driver = _make_driver_user("editother")
        self.kart = Kart.objects.create(
            name="Карт для правок", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
        )
        self.other_kart = Kart.objects.create(
            name="Чужой карт", chassis=self.chassis, chassis_type="junior", owner_driver=self.other_driver,
        )
        self.setup = Setup.objects.create(
            kart=self.kart, name="Исходный", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30, driver_weight_kg="60.0",
            weather="dry",
        )
        Ballast.objects.create(setup=self.setup, weight_kg=1, pos_x_mm=10, pos_y_mm=10, label="старый")
        self.client = Client()

    def _update_payload(self, **overrides):
        payload = {
            "setup_id": self.setup.id,
            "name": "Обновлено",
            "class_id": self.kart_class.id,
            "corners": {"lf": "31.0", "rf": "31.0", "lr": "31.0", "rr": "31.0"},
        }
        payload.update(overrides)
        return payload

    def test_requires_login(self):
        resp = self.client.post(
            "/balance/setup/save/", data=json.dumps(self._update_payload()), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 302)

    def test_foreign_setup_returns_404(self):
        self.client.force_login(self.other_user)
        resp = self.client.post(
            "/balance/setup/save/", data=json.dumps(self._update_payload()), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        self.setup.refresh_from_db()
        self.assertEqual(self.setup.name, "Исходный")

    def test_owner_can_update_values(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/", data=json.dumps(self._update_payload()), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.setup.refresh_from_db()
        self.assertEqual(self.setup.name, "Обновлено")
        self.assertEqual(str(self.setup.weight_lf), "31.0")
        self.assertEqual(Setup.objects.filter(kart=self.kart).count(), 1)  # не создан новый, тот же id

    def test_kart_id_in_payload_is_ignored(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/",
            data=json.dumps(self._update_payload(kart_id=self.other_kart.id)),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.setup.refresh_from_db()
        self.assertEqual(self.setup.kart_id, self.kart.id)  # карт не сменился

    def test_ballasts_replaced_wholesale(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/",
            data=json.dumps(self._update_payload(ballasts=[
                {"weight_kg": "3.0", "pos_x_mm": "50", "pos_y_mm": "60", "label": "новый"},
            ])),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        ballasts = list(Ballast.objects.filter(setup=self.setup))
        self.assertEqual(len(ballasts), 1)
        self.assertEqual(ballasts[0].label, "новый")

    def test_blank_driver_weight_clears_it_without_resurrection(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/",
            data=json.dumps(self._update_payload(driver_weight_kg="")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.setup.refresh_from_db()
        self.assertIsNone(self.setup.driver_weight_kg)

    def test_blank_name_keeps_previous_name(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            "/balance/setup/save/",
            data=json.dumps(self._update_payload(name="")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.setup.refresh_from_db()
        self.assertEqual(self.setup.name, "Исходный")

    def test_update_ignores_max_setups_per_kart_limit(self):
        from website import balance_setup_views
        original = balance_setup_views.MAX_SETUPS_PER_KART
        balance_setup_views.MAX_SETUPS_PER_KART = 1  # уже на пределе (единственный self.setup)
        try:
            self.client.force_login(self.driver_user)
            resp = self.client.post(
                "/balance/setup/save/", data=json.dumps(self._update_payload()), content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200, resp.content)
        finally:
            balance_setup_views.MAX_SETUPS_PER_KART = original

    def test_readonly_shared_setup_cannot_be_updated(self):
        team = Team.objects.create(name="Edit Team", slug="edit-team")
        team_kart = Kart.objects.create(name="Командный", chassis=self.chassis, chassis_type="junior", owner_team=team)
        roster_entry = TeamRosterEntry.objects.create(team=team, last_name="X", first_name="Y", driver=self.other_driver)
        team_kart.roster_entry = roster_entry
        team_kart.save()
        shared_setup = Setup.objects.create(
            kart=team_kart, name="Расшарено", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30, shared_with_driver=True,
        )
        self.client.force_login(self.other_user)
        resp = self.client.post(
            "/balance/setup/save/",
            data=json.dumps(self._update_payload(setup_id=shared_setup.id)),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        shared_setup.refresh_from_db()
        self.assertEqual(shared_setup.name, "Расшарено")


class SetupEditViewTests(TestCase):
    """website/balance_setup_views.py::setup_edit — Этап 4 (GET, рендерит home.html)."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()
        self.driver_user, self.driver = _make_driver_user("vieweditpilot")
        self.other_user, self.other_driver = _make_driver_user("vieweditother")
        self.kart = Kart.objects.create(
            name="Карт просмотра", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
        )
        self.setup = Setup.objects.create(
            kart=self.kart, name="Мой сетап", kart_class=self.kart_class,
            weight_lf=30, weight_rf=31, weight_lr=32, weight_rr=33,
        )
        self.client = Client()

    def test_requires_login(self):
        resp = self.client.get(f"/balance/setup/{self.setup.id}/")
        self.assertEqual(resp.status_code, 302)

    def test_foreign_setup_returns_404(self):
        self.client.force_login(self.other_user)
        resp = self.client.get(f"/balance/setup/{self.setup.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_owner_sees_editable_form(self):
        self.client.force_login(self.driver_user)
        resp = self.client.get(f"/balance/setup/{self.setup.id}/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="glCalcSavePanel"', html)
        self.assertIn('data-mode="edit"', html)
        self.assertIn("noindex, nofollow", html)

    def test_shared_viewer_sees_readonly_notice_not_form(self):
        team = Team.objects.create(name="View Team", slug="view-team")
        team_kart = Kart.objects.create(name="Командный просмотр", chassis=self.chassis, chassis_type="junior", owner_team=team)
        roster_entry = TeamRosterEntry.objects.create(team=team, last_name="X", first_name="Y", driver=self.other_driver)
        team_kart.roster_entry = roster_entry
        team_kart.save()
        shared_setup = Setup.objects.create(
            kart=team_kart, name="Только просмотр", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30, shared_with_driver=True,
        )
        self.client.force_login(self.other_user)
        resp = self.client.get(f"/balance/setup/{shared_setup.id}/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn('id="glCalcSavePanel"', html)
        self.assertIn("только для просмотра", html)

    def test_loaded_state_contains_saved_values(self):
        self.client.force_login(self.driver_user)
        resp = self.client.get(f"/balance/setup/{self.setup.id}/")
        html = resp.content.decode()
        m = re.search(r'id="balanceLoadedSetup"[^>]*>(.*?)</script>', html, re.S)
        self.assertIsNotNone(m)
        blob = json.loads(m.group(1))
        self.assertEqual(blob["state"]["corners"]["lf"], "30.0")
        self.assertTrue(blob["can_edit"])


class SetupCopyViewTests(TestCase):
    """website/balance_setup_views.py::setup_copy — Этап 5."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()
        self.driver_user, self.driver = _make_driver_user("copypilot")
        self.other_user, self.other_driver = _make_driver_user("copyother")
        self.kart = Kart.objects.create(
            name="Карт для копий", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
        )
        self.source = Setup.objects.create(
            kart=self.kart, name="Источник", kart_class=self.kart_class,
            weight_lf=30, weight_rf=31, weight_lr=32, weight_rr=33, driver_weight_kg="60.0",
            weather="wet", temp_air_c="20.0", temp_track_c="25.0", temp_source="auto",
            shared_with_team=True, wheelbase_mm=1000, track_front_mm=800, track_rear_mm=850,
        )
        Ballast.objects.create(setup=self.source, weight_kg=2, pos_x_mm=100, pos_y_mm=100, label="груз", sort_order=0)
        self.client = Client()

    def test_requires_login(self):
        resp = self.client.post(f"/balance/setup/{self.source.id}/copy/")
        self.assertEqual(resp.status_code, 302)

    def test_foreign_setup_returns_404(self):
        self.client.force_login(self.other_user)
        resp = self.client.post(f"/balance/setup/{self.source.id}/copy/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Setup.objects.filter(kart=self.kart).count(), 1)

    def test_readonly_shared_viewer_cannot_copy(self):
        # получателю шера копия бессмысленна (решение 2 плана) — та же
        # проверка can_edit_setup, что и у update/archive/share.
        team = Team.objects.create(name="Copy Team", slug="copy-team")
        team_kart = Kart.objects.create(name="Командный", chassis=self.chassis, chassis_type="junior", owner_team=team)
        roster_entry = TeamRosterEntry.objects.create(team=team, last_name="X", first_name="Y", driver=self.other_driver)
        team_kart.roster_entry = roster_entry
        team_kart.save()
        shared_setup = Setup.objects.create(
            kart=team_kart, name="Расшарено", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30, shared_with_driver=True,
        )
        self.client.force_login(self.other_user)
        resp = self.client.post(f"/balance/setup/{shared_setup.id}/copy/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Setup.objects.filter(kart=team_kart).count(), 1)

    def test_owner_copy_resets_fields_per_plan_table(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(f"/balance/setup/{self.source.id}/copy/")
        self.assertEqual(resp.status_code, 200, resp.content)
        copy_id = json.loads(resp.content)["id"]
        copy = Setup.objects.get(pk=copy_id)

        # копируется
        self.assertEqual(copy.kart_id, self.kart.id)
        self.assertEqual(copy.kart_class_id, self.kart_class.id)
        self.assertEqual(str(copy.weight_lf), "30.0")
        self.assertEqual(str(copy.driver_weight_kg), "60.0")
        self.assertEqual(copy.wheelbase_mm, 1000)
        self.assertEqual(list(copy.ballasts.values_list("label", flat=True)), ["груз"])

        # сбрасывается
        self.assertEqual(copy.weather, "dry")
        self.assertIsNone(copy.temp_air_c)
        self.assertIsNone(copy.temp_track_c)
        self.assertEqual(copy.temp_source, "manual")
        self.assertIsNone(copy.track_id)
        self.assertEqual(copy.notes, "")
        self.assertFalse(copy.shared_with_team)
        self.assertFalse(copy.shared_with_driver)
        self.assertFalse(copy.is_archived)

        # новое значение
        self.assertEqual(copy.name, "Источник — копия")
        self.assertEqual(copy.parent_setup_id, self.source.id)

    def test_copying_archived_source_gives_non_archived_copy(self):
        self.source.is_archived = True
        self.source.save(update_fields=["is_archived"])
        self.client.force_login(self.driver_user)
        resp = self.client.post(f"/balance/setup/{self.source.id}/copy/")
        self.assertEqual(resp.status_code, 200, resp.content)
        copy = Setup.objects.get(pk=json.loads(resp.content)["id"])
        self.assertFalse(copy.is_archived)

    def test_max_setups_per_kart_enforced_on_copy(self):
        from website import balance_setup_views
        original = balance_setup_views.MAX_SETUPS_PER_KART
        balance_setup_views.MAX_SETUPS_PER_KART = 1  # источник уже занимает единственное место
        try:
            self.client.force_login(self.driver_user)
            resp = self.client.post(f"/balance/setup/{self.source.id}/copy/")
            self.assertEqual(resp.status_code, 400)
        finally:
            balance_setup_views.MAX_SETUPS_PER_KART = original


class SetupArchiveViewTests(TestCase):
    """website/balance_setup_views.py::setup_archive — Этап 6 (уровень Setup,
    отдельно от kart_archive)."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()
        self.driver_user, self.driver = _make_driver_user("archivepilot")
        self.other_user, self.other_driver = _make_driver_user("archiveother")
        self.kart = Kart.objects.create(
            name="Карт для архива", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
        )
        self.setup = Setup.objects.create(
            kart=self.kart, name="Сетап", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30,
        )
        self.client = Client()

    def test_requires_login(self):
        resp = self.client.post(f"/balance/setup/{self.setup.id}/archive/")
        self.assertEqual(resp.status_code, 302)

    def test_foreign_setup_returns_404_not_403(self):
        self.client.force_login(self.other_user)
        resp = self.client.post(
            f"/balance/setup/{self.setup.id}/archive/",
            data=json.dumps({"archived": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        self.setup.refresh_from_db()
        self.assertFalse(self.setup.is_archived)

    def test_owner_can_toggle_and_row_stays_in_db(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            f"/balance/setup/{self.setup.id}/archive/",
            data=json.dumps({"archived": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.setup.refresh_from_db()
        self.assertTrue(self.setup.is_archived)
        self.assertTrue(Setup.objects.filter(pk=self.setup.pk).exists())  # мягкое архивирование

        resp2 = self.client.post(
            f"/balance/setup/{self.setup.id}/archive/",
            data=json.dumps({"archived": False}), content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 200)
        self.setup.refresh_from_db()
        self.assertFalse(self.setup.is_archived)


class SetupShareViewTests(TestCase):
    """website/balance_setup_views.py::setup_share — Этап 6. target=team
    валиден только для личного карта пилота, target=driver — только для
    карта команды с закреплённым в ростере пилотом (см. visible_setups_for_user)."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()
        self.driver_user, self.driver = _make_driver_user("sharepilot")
        self.other_user, self.other_driver = _make_driver_user("shareother")
        self.team = Team.objects.create(name="Share Team", slug="share-team")

        self.personal_kart = Kart.objects.create(
            name="Личный карт", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
        )
        self.personal_setup = Setup.objects.create(
            kart=self.personal_kart, name="Личный сетап", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30,
        )

        self.team_kart_with_roster = Kart.objects.create(
            name="Командный (с ростером)", chassis=self.chassis, chassis_type="junior", owner_team=self.team,
        )
        roster_entry = TeamRosterEntry.objects.create(
            team=self.team, last_name="X", first_name="Y", driver=self.driver,
        )
        self.team_kart_with_roster.roster_entry = roster_entry
        self.team_kart_with_roster.save()
        self.team_setup = Setup.objects.create(
            kart=self.team_kart_with_roster, name="Командный сетап", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30,
        )

        self.team_kart_no_roster = Kart.objects.create(
            name="Командный (без ростера)", chassis=self.chassis, chassis_type="junior", owner_team=self.team,
        )
        self.team_setup_no_roster = Setup.objects.create(
            kart=self.team_kart_no_roster, name="Без ростера", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30,
        )

        self.manager_user = _make_manager_user("sharemanager", self.team)
        self.client = Client()

    def test_requires_login(self):
        resp = self.client.post(f"/balance/setup/{self.personal_setup.id}/share/")
        self.assertEqual(resp.status_code, 302)

    def test_foreign_setup_returns_404(self):
        self.client.force_login(self.other_user)
        resp = self.client.post(
            f"/balance/setup/{self.personal_setup.id}/share/",
            data=json.dumps({"target": "team", "shared": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_personal_kart_can_share_with_team(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            f"/balance/setup/{self.personal_setup.id}/share/",
            data=json.dumps({"target": "team", "shared": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.personal_setup.refresh_from_db()
        self.assertTrue(self.personal_setup.shared_with_team)

    def test_personal_kart_cannot_share_with_driver_target(self):
        # У личного карта нет "закреплённого пилота" — цель driver бессмысленна.
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            f"/balance/setup/{self.personal_setup.id}/share/",
            data=json.dumps({"target": "driver", "shared": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.personal_setup.refresh_from_db()
        self.assertFalse(self.personal_setup.shared_with_driver)

    def test_team_kart_with_roster_can_share_with_driver(self):
        self.client.force_login(self.manager_user)
        resp = self.client.post(
            f"/balance/setup/{self.team_setup.id}/share/",
            data=json.dumps({"target": "driver", "shared": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.team_setup.refresh_from_db()
        self.assertTrue(self.team_setup.shared_with_driver)

    def test_team_kart_cannot_share_with_team_target(self):
        # kart.owner_team, не owner_driver — цель team здесь не резолвится
        # visible_setups_for_user вообще (тот управляющий team и так видит
        # карт команды напрямую, независимо от shared_with_team).
        self.client.force_login(self.manager_user)
        resp = self.client.post(
            f"/balance/setup/{self.team_setup.id}/share/",
            data=json.dumps({"target": "team", "shared": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_team_kart_without_roster_cannot_share_with_driver(self):
        self.client.force_login(self.manager_user)
        resp = self.client.post(
            f"/balance/setup/{self.team_setup_no_roster.id}/share/",
            data=json.dumps({"target": "driver", "shared": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_target_rejected(self):
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            f"/balance/setup/{self.personal_setup.id}/share/",
            data=json.dumps({"target": "bogus", "shared": True}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_can_unshare(self):
        self.personal_setup.shared_with_team = True
        self.personal_setup.save(update_fields=["shared_with_team"])
        self.client.force_login(self.driver_user)
        resp = self.client.post(
            f"/balance/setup/{self.personal_setup.id}/share/",
            data=json.dumps({"target": "team", "shared": False}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.personal_setup.refresh_from_db()
        self.assertFalse(self.personal_setup.shared_with_team)


class SetupsListViewTests(TestCase):
    """website/balance_setup_views.py::setups_list — Этап 3 (только чтение,
    вся фильтрация/группировка на клиенте — здесь проверяется только то,
    что видит сервер, а не JS-рендер)."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()
        self.driver_user, self.driver = _make_driver_user("listpilot")
        self.other_user, self.other_driver = _make_driver_user("listother")
        self.team = Team.objects.create(name="List Team", slug="list-team")
        self.manager_user = _make_manager_user("listmanager", self.team)

        self.own_kart = Kart.objects.create(
            name="Личный карт", chassis=self.chassis, chassis_type="junior", owner_driver=self.driver,
        )
        self.team_kart = Kart.objects.create(
            name="Командный карт", chassis=self.chassis, chassis_type="junior", owner_team=self.team,
        )
        self.client = Client()

    def test_requires_login(self):
        resp = self.client.get("/balance/mine/")
        self.assertEqual(resp.status_code, 302)

    def test_no_identity_sees_empty_list(self):
        plain = User.objects.create_user(username="plainlist", email="pl@example.com", password="x")
        self.client.force_login(plain)
        resp = self.client.get("/balance/mine/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["setups_data"], [])
        self.assertFalse(resp.context["has_balance_access"])

    def test_driver_sees_only_own_setups(self):
        Setup.objects.create(
            kart=self.own_kart, name="Моё", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30,
        )
        Setup.objects.create(
            kart=self.team_kart, name="Не моё", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30,
        )
        self.client.force_login(self.driver_user)
        resp = self.client.get("/balance/mine/")
        names = {row["name"] for row in resp.context["setups_data"]}
        self.assertEqual(names, {"Моё"})

    def test_includes_archived_for_client_side_toggle(self):
        Setup.objects.create(
            kart=self.own_kart, name="Архивный", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30, is_archived=True,
        )
        self.client.force_login(self.driver_user)
        resp = self.client.get("/balance/mine/")
        rows = resp.context["setups_data"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_archived"])

    def test_shared_with_driver_setup_marked_read_only(self):
        roster_entry = TeamRosterEntry.objects.create(team=self.team, last_name="X", first_name="Y", driver=self.driver)
        self.team_kart.roster_entry = roster_entry
        self.team_kart.save()
        Setup.objects.create(
            kart=self.team_kart, name="Расшарено пилоту", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30, shared_with_driver=True,
        )
        self.client.force_login(self.driver_user)
        resp = self.client.get("/balance/mine/")
        rows = resp.context["setups_data"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["can_edit"])

    def test_manager_sees_team_kart_setups_as_editable(self):
        Setup.objects.create(
            kart=self.team_kart, name="Командный сетап", kart_class=self.kart_class,
            weight_lf=30, weight_rf=30, weight_lr=30, weight_rr=30,
        )
        self.client.force_login(self.manager_user)
        resp = self.client.get("/balance/mine/")
        rows = resp.context["setups_data"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["can_edit"])
        self.assertTrue(resp.context["has_balance_access"])

    def test_response_is_noindex(self):
        self.client.force_login(self.driver_user)
        resp = self.client.get("/balance/mine/")
        self.assertContains(resp, "noindex, nofollow")


class TabbarAccessTests(TestCase):
    """app_base.html — вкладка «Мои сетапы» становится реальной ссылкой
    только при has_balance_access (иначе disabled span, как раньше)."""

    def setUp(self):
        self.chassis, self.kart_class = BalanceTestData.build()
        self.driver_user, self.driver = _make_driver_user("tabpilot")
        self.client = Client()

    def test_disabled_for_anonymous(self):
        resp = self.client.get("/balance/")
        self.assertContains(resp, "gl-balance-tab--disabled")
        self.assertNotContains(resp, 'href="/balance/mine/"')

    def test_enabled_for_driver(self):
        self.client.force_login(self.driver_user)
        resp = self.client.get("/balance/")
        self.assertContains(resp, 'href="/balance/mine/"')
        self.assertNotContains(resp, "gl-balance-tab--disabled")

    def test_disabled_for_authenticated_without_identity(self):
        plain = User.objects.create_user(username="tabplain", email="tp@example.com", password="x")
        self.client.force_login(plain)
        resp = self.client.get("/balance/")
        self.assertContains(resp, "gl-balance-tab--disabled")


class RateLimitTests(TestCase):
    def test_balance_ratelimit_returns_429_over_limit(self):
        from django.core.cache import cache
        from website.services.balance_limits import balance_ratelimit

        calls = []

        @balance_ratelimit("test_key", limit=2, window_seconds=60)
        def view(request):
            calls.append(1)
            from django.http import HttpResponse
            return HttpResponse("ok")

        class FakeRequest:
            META = {"REMOTE_ADDR": "10.0.0.1"}

        cache.delete("balance:rl:test_key:10.0.0.1")
        r1 = view(FakeRequest())
        r2 = view(FakeRequest())
        r3 = view(FakeRequest())
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 429)
        self.assertEqual(len(calls), 2)
