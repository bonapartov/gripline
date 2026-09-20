import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta

from organizers.models import Championship, OrganizerProfile, Stage
from .models import Application, ApplicationDocument, ApplicationPayment, StageDocument


class ApplicationFileAccessTests(TestCase):
    """
    serve_document/serve_receipt (applications/views.py) — регресс на
    находку security-аудита (коммит 16d0b90): detail.html раньше ссылался
    прямо на doc.file.url/payment.receipt_file.url — публичный /media/ путь
    без проверки прав. Теперь файл отдаёт только заявитель или организатор
    этапа, посторонний авторизованный пользователь получает отказ, а не файл.
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
        self.organizer_user = User.objects.create_user(
            username="fileacc-org", email="fileacc-org@example.com", password="x",
        )
        self.organizer = OrganizerProfile.objects.create(user=self.organizer_user)
        self.championship = Championship.objects.create(
            organizer=self.organizer, title="Чемпионат", slug="fileacc-champ",
        )
        self.stage = Stage.objects.create(
            championship=self.championship, title="Этап",
            start_date=timezone.now(), end_date=timezone.now() + timedelta(hours=6),
        )

        self.applicant = User.objects.create_user(
            username="fileacc-applicant", email="fileacc-applicant@example.com", password="x",
        )
        self.other_user = User.objects.create_user(
            username="fileacc-other", email="fileacc-other@example.com", password="x",
        )

        self.application = Application.objects.create(
            stage=self.stage, submitted_by=self.applicant, entry_fee_amount=1000,
        )
        self.stage_document = StageDocument.objects.create(stage=self.stage, name="Паспорт")
        self.document = ApplicationDocument.objects.create(
            application=self.application, stage_document=self.stage_document,
            file=SimpleUploadedFile("passport.jpg", b"fake-passport-bytes"),
        )
        self.payment = ApplicationPayment.objects.create(
            application=self.application, amount=1000,
            receipt_file=SimpleUploadedFile("receipt.jpg", b"fake-receipt-bytes"),
        )

    def _doc_url(self):
        return f"/applications/document/{self.document.id}/file/"

    def _receipt_url(self):
        return f"/applications/{self.application.id}/receipt/"

    def test_anonymous_redirected_from_document(self):
        resp = self.client.get(self._doc_url())
        self.assertEqual(resp.status_code, 302)

    def test_anonymous_redirected_from_receipt(self):
        resp = self.client.get(self._receipt_url())
        self.assertEqual(resp.status_code, 302)

    def test_owner_can_download_document(self):
        self.client.force_login(self.applicant)
        resp = self.client.get(self._doc_url())
        self.assertEqual(resp.status_code, 200)

    def test_owner_can_download_receipt(self):
        self.client.force_login(self.applicant)
        resp = self.client.get(self._receipt_url())
        self.assertEqual(resp.status_code, 200)

    def test_organizer_can_download_document(self):
        self.client.force_login(self.organizer_user)
        resp = self.client.get(self._doc_url())
        self.assertEqual(resp.status_code, 200)

    def test_organizer_can_download_receipt(self):
        self.client.force_login(self.organizer_user)
        resp = self.client.get(self._receipt_url())
        self.assertEqual(resp.status_code, 200)

    def test_unrelated_user_denied_document(self):
        self.client.force_login(self.other_user)
        resp = self.client.get(self._doc_url())
        self.assertEqual(resp.status_code, 403)

    def test_unrelated_user_denied_receipt(self):
        self.client.force_login(self.other_user)
        resp = self.client.get(self._receipt_url())
        self.assertEqual(resp.status_code, 403)
