from django.test import SimpleTestCase

from website.schema import render_json_ld


class RenderJsonLdEscapingTests(SimpleTestCase):
    """
    render_json_ld() (website/schema.py) — регресс на находку security-
    аудита (коммит 16d0b90): голый json.dumps без экранирования пропускал
    буквальную подстроку "</script>" внутрь <script type="application/
    ld+json">. Любое поле с пользовательским текстом (biography, telegram,
    описание команды/трассы), содержащее "</script>", пробивало тег и
    внедряло произвольный HTML/JS — хранимый XSS на страницах пилота/
    команды/трассы и везде, где есть breadcrumbs. Экранирование как в
    django.utils.html.json_script.
    """

    def test_script_breakout_sequence_is_escaped(self):
        payload = str(render_json_ld({"name": "</script><script>alert(1)</script>"}))
        self.assertNotIn("</script><script>alert(1)</script>", payload)
        self.assertIn("\\u003c/script\\u003e", payload)

    def test_still_wrapped_as_ld_json_script_tag(self):
        payload = str(render_json_ld({"name": "ok"}))
        self.assertTrue(payload.startswith('<script type="application/ld+json">'))
        self.assertTrue(payload.endswith("</script>"))

    def test_empty_data_returns_empty_string(self):
        self.assertEqual(render_json_ld({}), "")
        self.assertEqual(render_json_ld(None), "")
