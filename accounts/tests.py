from django.contrib.auth.models import User
from django.test import TestCase


class BalanceNextRedirectTests(TestCase):
    """
    accounts/views.py::profile() — возврат на /balance/ после входа через
    Яндекс (Блок 3 ТЗ /balance/, Этап 2 — см.
    /home/v/.claude/plans/smooth-snacking-spindle.md, решение 4).

    Проверяется в самом начале profile(), а не только в _redirect_by_role:
    у пилота с уже одобренной заявкой (самый частый повторный вход)
    profile() рендерит профиль напрямую и до _redirect_by_role в принципе
    не добирается — если бы редирект жил только там, этот (самый частый)
    случай остался бы непокрытым.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="balanceuser", email="bu@example.com", password="x")

    def _set_session(self, **kwargs):
        session = self.client.session
        for key, value in kwargs.items():
            session[key] = value
        session.save()

    def test_redirects_to_balance_next_when_present(self):
        self.client.force_login(self.user)
        self._set_session(yandex_balance_next="/balance/")
        resp = self.client.get("/accounts/profile/")
        self.assertRedirects(resp, "/balance/", fetch_redirect_response=False)

    def test_does_not_redirect_during_fresh_onboarding(self):
        # Свежий OAuth-онбординг (пилот ещё не подал заявку) — yandex_next
        # игнорируется, пользователь идёт по обычному пути (у него ещё нет
        # Driver, /balance/ ему рано).
        self.client.force_login(self.user)
        self._set_session(yandex_balance_next="/balance/", yandex_onboarding=True)
        resp = self.client.get("/accounts/profile/")
        if resp.status_code == 302:
            self.assertNotEqual(resp.url, "/balance/")

    def test_balance_next_is_consumed_once(self):
        self.client.force_login(self.user)
        self._set_session(yandex_balance_next="/balance/")
        self.client.get("/accounts/profile/")
        self.assertNotIn("yandex_balance_next", self.client.session)

    def test_no_redirect_without_balance_next(self):
        self.client.force_login(self.user)
        resp = self.client.get("/accounts/profile/")
        if resp.status_code == 302:
            self.assertNotEqual(resp.url, "/balance/")
