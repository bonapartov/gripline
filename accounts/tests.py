import json
import shutil
import tempfile

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings

from .models import PilotDocument


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


class ServePilotDocumentTests(TestCase):
    """
    serve_pilot_document (accounts/views.py) — регресс на находку
    security-аудита (коммит 16d0b90): шаблон профиля и AJAX-ответ загрузки
    раньше ссылались прямо на doc.file.url — публичный /media/ путь, который
    nginx отдавал БЕЗ проверки прав, а Django не рандомизирует имя файла на
    первой загрузке. Теперь единственный путь к файлу — эта вьюха с
    проверкой владельца.
    """

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

    def setUp(self):
        self.owner = User.objects.create_user(username="docowner", email="docowner@example.com", password="x")
        self.stranger = User.objects.create_user(username="docstranger", email="docstranger@example.com", password="x")
        # UserProfile создаётся сигналом accounts.signals.create_user_profile
        # при сохранении User — создавать вручную повторно нельзя (OneToOne).
        self.doc = PilotDocument.objects.create(
            profile=self.owner.profile, name="Паспорт",
            file=SimpleUploadedFile("passport.jpg", b"fake-passport-bytes"),
        )

    def _url(self):
        return f"/accounts/documents/{self.doc.id}/file/"

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 302)

    def test_owner_can_download(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_served_as_attachment_not_inline(self):
        # as_attachment=True — иначе браузер рендерит файл inline на origin
        # gripline.ru по Content-Type, угаданному из имени файла: пилот мог
        # бы назвать документ evil.html со скриптом внутри (см. коммит
        # security-аудита). Регресс именно на это, не на скачивание как таковое.
        self.client.force_login(self.owner)
        resp = self.client.get(self._url())
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))

    def test_stranger_gets_404_not_the_file(self):
        self.client.force_login(self.stranger)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 404)


class ProcessClaimCsrfTests(TestCase):
    """
    process_claim_api (accounts/views.py) — @csrf_exempt был снят
    security-аудитом (коммит 16d0b90): вьюха меняет состояние (одобряет/
    отклоняет заявку пилота) и раньше принимала POST без CSRF-токена вообще.
    Шаблон driver_claim_admin_page.html уже отправляет X-CSRFToken, так что
    снятие exempt не требовало правок фронтенда.
    """

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="staffcsrf", email="staffcsrf@example.com", password="x", is_staff=True,
        )

    def test_post_without_csrf_token_is_rejected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff_user)
        resp = csrf_client.post(
            "/accounts/api/process-claim/",
            data=json.dumps({"claim_id": 1, "action": "reject"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)


class AxesLockoutTests(TestCase):
    """
    django-axes (security-аудит, п.4 приоритетного списка) — rate-limit на
    login-формы. accounts/views.py::login_view не использует Django
    AuthenticationForm/LoginView, а вызывает authenticate() напрямую — но это
    не требует отдельной интеграции: django.contrib.auth.authenticate() сам
    шлёт сигнал user_login_failed при любом провале (включая PermissionDenied
    от AxesBackend), независимо от вызывающей вьюхи. Блокировка — по паре
    (username, ip_address) (AXES_LOCKOUT_PARAMETERS), не по одному IP, иначе
    один атакующий за тем же NAT/прокси блокировал бы всех.
    """

    def setUp(self):
        self.email = "axesuser@example.com"
        self.password = "CorrectHorseBattery9!"
        self.user = User.objects.create_user(
            username=self.email, email=self.email, password=self.password, is_active=True,
        )

    def _authenticate(self, password, remote_addr="203.0.113.10"):
        """
        Прямой вызов django.contrib.auth.authenticate() через RequestFactory —
        то же самое, что делает login_view изнутри, но без похода через полный
        HTTP-цикл. AxesMiddleware вызывает get_response() ДО того, как решает,
        подменять ли ответ — то есть даже заблокированный axes запрос сначала
        полностью отрабатывает вьюху, включая render(request,
        'accounts/login.html') при неверных данных. Тестовая БД
        (--no-migrations, как во всём проекте, см. teams/tests.py) не содержит
        Wagtail Site/LayoutSettings, и это падает независимо от axes — что
        сделало бы HTTP-тест неотличимым по причине падения (неверный пароль
        vs блокировка). Здесь же проверяется именно то, за что отвечает axes:
        сам authenticate() — без захода в шаблоны вообще.
        """
        request = RequestFactory().post("/accounts/login/", REMOTE_ADDR=remote_addr)
        request.session = self.client.session
        return authenticate(request, username=self.email, password=password)

    def test_locks_out_after_failure_limit_from_same_ip(self):
        from django.conf import settings

        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.assertIsNone(self._authenticate("wrong-password"))

        # Лимит исчерпан — даже ПРАВИЛЬНЫЙ пароль с того же IP не пускает.
        self.assertIsNone(self._authenticate(self.password))

    def test_does_not_lock_out_same_username_from_different_ip(self):
        from django.conf import settings

        for _ in range(settings.AXES_FAILURE_LIMIT):
            self._authenticate("wrong-password", remote_addr="203.0.113.10")

        # Тот же пользователь, но с другого IP — блокировка per (username, ip),
        # не глобальная по username, поэтому вход разрешён.
        user = self._authenticate(self.password, remote_addr="198.51.100.20")
        self.assertEqual(user, self.user)
