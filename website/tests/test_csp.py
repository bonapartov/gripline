from django.test import Client, SimpleTestCase

from mysite.security import build_csp_header_value


class BuildCspHeaderValueTests(SimpleTestCase):
    def test_joins_directives_and_sources(self):
        header = build_csp_header_value({
            "default-src": ["'self'"],
            "img-src": ["'self'", "data:"],
        })
        self.assertEqual(header, "default-src 'self'; img-src 'self' data:")

    def test_directive_without_sources_is_kept_bare(self):
        header = build_csp_header_value({"upgrade-insecure-requests": []})
        self.assertEqual(header, "upgrade-insecure-requests")


class CspReportOnlyMiddlewareTests(SimpleTestCase):
    """
    security-аудит, п.5 — наблюдательная фаза CSP. Заголовок должен стоять
    на КАЖДОМ ответе (одинаковое значение для всех, поэтому безопасно для
    wagtailcache — см. docstring ContentSecurityPolicyReportOnlyMiddleware),
    report-uri должен указывать на реальный работающий эндпоинт.
    """

    def test_header_present_on_response(self):
        resp = self.client.get("/csp-report/")  # любой существующий путь
        self.assertIn("Content-Security-Policy-Report-Only", resp)
        self.assertIn("report-uri /csp-report/", resp["Content-Security-Policy-Report-Only"])


class CspReportViewTests(SimpleTestCase):
    """website/csp_views.py::csp_report — приёмник браузерных отчётов."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_accepts_report_without_csrf_token(self):
        # @csrf_exempt намеренно: браузер шлёт этот POST сам, без доступа
        # к CSRF-токену страницы (см. docstring вьюхи).
        resp = self.client.post(
            "/csp-report/",
            data='{"csp-report": {"blocked-uri": "https://evil.example/x.js"}}',
            content_type="application/csp-report",
        )
        self.assertEqual(resp.status_code, 204)

    def test_rejects_invalid_json(self):
        resp = self.client.post("/csp-report/", data="not json", content_type="application/csp-report")
        self.assertEqual(resp.status_code, 400)

    def test_rejects_get(self):
        resp = self.client.get("/csp-report/")
        self.assertEqual(resp.status_code, 405)

    def test_rejects_oversized_body(self):
        resp = self.client.post(
            "/csp-report/",
            data="x" * 9000,
            content_type="application/csp-report",
        )
        self.assertEqual(resp.status_code, 413)

    def test_logs_violation_payload(self):
        with self.assertLogs("gripline.csp", level="WARNING") as cm:
            self.client.post(
                "/csp-report/",
                data='{"csp-report": {"blocked-uri": "https://evil.example/x.js"}}',
                content_type="application/csp-report",
            )
        self.assertIn("CSP-VIOLATION", cm.output[0])
        self.assertIn("evil.example", cm.output[0])
