from types import SimpleNamespace as NS

from django.contrib.auth.models import User
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings

LOGO = 'website/images/email/gripline-logo.png'


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    BASE_URL='https://gripline.ru',
    ALLOWED_HOSTS=['*'],
)
class EmailTemplatesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'ivan', 'ivan@example.ru', 'pass-12345', first_name='Иван', last_name='Смирнов')
        self.request = RequestFactory().get('/', HTTP_HOST='gripline.ru', secure=True)
        self.driver = NS(full_name='Иван Смирнов', get_absolute_url=lambda: '/drivers/ivan/')

    def last(self):
        msg = mail.outbox[-1]
        html = dict((t, c) for c, t in msg.alternatives)['text/html']
        return msg, html

    def assert_branded(self, html, text):
        self.assertIn('https://gripline.ru/static/' + LOGO, html)
        self.assertIn('Письмо отправлено автоматически', html)
        self.assertIn('gripline.ru', text)
        self.assertNotIn('{{', html + text)
        self.assertNotIn('{%', html + text)

    def test_verification_emails(self):
        from accounts.views import send_verification_email
        from organizers.views import send_organizer_verification_email
        from teams.views import send_team_verification_email

        for fn, path in ((send_verification_email, '/accounts/verify-email/'),
                         (send_team_verification_email, '/teams/verify-email/'),
                         (send_organizer_verification_email, '/organizers/verify-email/')):
            fn(self.user, self.request)
            msg, html = self.last()
            self.assert_branded(html, msg.body)
            self.assertIn('https://gripline.ru' + path, msg.body)
            self.assertIn('Подтвердить e-mail', html)
            self.assertIn('30 мин.', msg.body)
            self.assertIn('Здравствуйте, Иван Смирнов!', msg.body)

    def test_password_reset(self):
        self.client.post('/accounts/password-reset/', {'email': 'ivan@example.ru'})
        msg, html = self.last()
        self.assertEqual(msg.subject, 'Сброс пароля на gripline.ru')
        self.assert_branded(html, msg.body)
        self.assertIn('/accounts/password-reset/', msg.body)
        self.assertIn('Задать новый пароль', html)

    def test_claim_emails_escape_admin_comment(self):
        from accounts.signals import (send_driver_claim_approved_email, send_driver_claim_pending_email,
                                      send_driver_claim_rejected_email)
        send_driver_claim_pending_email(self.user, NS(driver=self.driver))
        send_driver_claim_approved_email(self.user, self.driver)
        send_driver_claim_rejected_email(self.user, NS(driver=self.driver, admin_comment='<b>нет</b> лицензии'))
        self.assertEqual(len(mail.outbox), 3)
        msg, html = self.last()
        self.assert_branded(html, msg.body)
        self.assertIn('&lt;b&gt;нет&lt;/b&gt; лицензии', html)
        self.assertNotIn('<b>нет</b>', html)
        self.assertIn('<b>нет</b> лицензии', msg.body)

    def test_team_invitation(self):
        from teams.views import _send_team_invitation_email
        team = NS(name='Kart Lab', manager_name='Алексей Воронов')
        _send_team_invitation_email(self.driver, team, self.user, NS(pk=42, race_class=NS(name='Супер-мини')))
        msg, html = self.last()
        self.assert_branded(html, msg.body)
        self.assertEqual(msg.subject, 'Приглашение в команду Kart Lab')
        self.assertIn('Супер-мини', html)
        self.assertIn('Отклонить', html)
        self.assertIn('Принять приглашение', html)
        self.assertIn('/42/', msg.body)

    def _application(self):
        stage = NS(title='3-й этап', championship=NS(title='Кубок Подмосковья'))
        return NS(id=318, stage=stage, pilot=NS(full_name='Иван Смирнов'), submitted_by=self.user)

    def test_application_notices_all_kinds(self):
        from applications.views import _NOTICES, _notify
        doc = NS(name='Медицинская справка')
        for kind in _NOTICES:
            _notify(self._application(), kind, comment='<script>x</script>', document=doc)
            msg, html = self.last()
            self.assert_branded(html, msg.body)
            self.assertIn('3-й этап', msg.subject)
            self.assertIn('https://gripline.ru/applications/318/', html)
            self.assertNotIn('<script>x', html)
        self.assertEqual(len(mail.outbox), len(_NOTICES))

    def test_app_link_uses_base_url(self):
        # регрессия: _app_link падал NameError (не был импортирован settings),
        # из-за чего действия организатора с заявками отдавали 500
        from applications.views import _app_link
        self.assertEqual(_app_link(NS(id=5)), 'https://gripline.ru/applications/5/')

    def test_admin_notifications_use_compact_layout(self):
        from accounts.views import send_admin_notification
        from teams.views import send_team_admin_notification
        send_admin_notification('пилотом', {'user_email': 'ivan@example.ru', 'first_name': 'Иван',
                                            'last_name': 'Смирнов', 'city': '', 'driver_name': 'Иван Смирнов'})
        send_team_admin_notification({'user_email': 'm@kartlab.example', 'team_name': '<Kart Lab>'})
        self.assertEqual(len(mail.outbox), 2)
        first_html = dict((t, c) for c, t in mail.outbox[0].alternatives)['text/html']
        self.assertIn('Администратору', first_html)
        self.assertIn('Служебное уведомление', first_html)
        self.assertNotIn('Город', first_html)
        msg, html = self.last()
        self.assertEqual(msg.subject, '[Gripline] Новая заявка от команды')
        self.assertIn('&lt;Kart Lab&gt;', html)
        self.assertIn('https://gripline.ru/admin/', msg.body)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    BASE_URL='https://gripline.ru',
    ALLOWED_HOSTS=['*'],
)
class EmailLinksWorkTests(TestCase):
    """Ссылки из писем реально открываются: подтверждение активирует аккаунт, сброс ведёт на форму."""

    def _links(self, msg):
        import re
        html = dict((t, c) for c, t in msg.alternatives)['text/html']
        text_links = re.findall(r'https://gripline\.ru/\S+', msg.body)
        html_links = [h.replace('&amp;', '&') for h in re.findall(r'href="(https://gripline\.ru/[^"]*)"', html)]
        return text_links, html_links

    def _check_verification(self, send, path_prefix):
        from urllib.parse import urlparse
        user = User.objects.create_user('new', 'new@example.ru', 'pass-12345', first_name='Пётр', is_active=False)
        send(user, RequestFactory().get('/', HTTP_HOST='gripline.ru', secure=True))
        text_links, html_links = self._links(mail.outbox[-1])
        link = next(u for u in text_links if path_prefix in u)
        self.assertIn(link, html_links, 'ссылка в кнопке и в тексте должна совпадать')
        response = self.client.get(urlparse(link).path, HTTP_HOST='gripline.ru', secure=True)
        self.assertIn(response.status_code, (200, 302))
        user.refresh_from_db()
        self.assertTrue(user.is_active, f'переход по {link} не активировал аккаунт')

    def test_pilot_verification_link_activates_account(self):
        from accounts.views import send_verification_email
        self._check_verification(send_verification_email, '/accounts/verify-email/')

    def test_team_verification_link_activates_account(self):
        from teams.views import send_team_verification_email
        self._check_verification(send_team_verification_email, '/teams/verify-email/')

    def test_organizer_verification_link_activates_account(self):
        from organizers.views import send_organizer_verification_email
        self._check_verification(send_organizer_verification_email, '/organizers/verify-email/')

    def test_password_reset_link_opens_new_password_form(self):
        from urllib.parse import urlparse
        User.objects.create_user('ivan', 'ivan@example.ru', 'pass-12345')
        self.client.post('/accounts/password-reset/', {'email': 'ivan@example.ru'}, HTTP_HOST='gripline.ru', secure=True)
        text_links, html_links = self._links(mail.outbox[-1])
        link = next(u for u in text_links if '/accounts/password-reset/' in u)
        self.assertIn(link, html_links)
        # PasswordResetConfirmView редиректит на set-password только при валидном токене
        response = self.client.get(urlparse(link).path, HTTP_HOST='gripline.ru', secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].endswith('/set-password/'))

    def test_every_internal_link_resolves(self):
        from urllib.parse import urlparse
        from django.urls import Resolver404, resolve
        from accounts.signals import send_driver_claim_approved_email, send_driver_claim_pending_email
        from accounts.views import send_admin_notification
        from applications.views import _NOTICES, _notify
        from teams.views import _send_team_invitation_email

        user = User.objects.create_user('ivan', 'ivan@example.ru', 'pass-12345')
        driver = NS(full_name='Иван Смирнов', get_absolute_url=lambda: '/drivers/ivan/')
        send_driver_claim_pending_email(user, NS(driver=driver))
        send_driver_claim_approved_email(user, driver)
        _send_team_invitation_email(driver, NS(name='Kart Lab'), user, NS(pk=42, race_class=None))
        app = NS(id=318, stage=NS(title='Этап', championship=NS(title='Кубок')),
                 pilot=NS(full_name='Иван'), submitted_by=user)
        for kind in _NOTICES:
            _notify(app, kind, 'комментарий', document=NS(name='Справка'))
        send_admin_notification('пилотом', {'user_email': 'ivan@example.ru', 'first_name': 'Иван'})

        checked = set()
        for msg in mail.outbox:
            text_links, html_links = self._links(msg)
            for link in set(text_links) | set(html_links):
                path = urlparse(link).path
                if path.startswith('/static/') or path in checked:
                    continue
                checked.add(path)
                try:
                    resolve(path)
                except Resolver404:
                    self.fail(f'{msg.subject}: ссылка {link} никуда не ведёт')
        self.assertGreaterEqual(len(checked), 7)


class LoginRedirectTests(TestCase):
    """Ссылки из писем на закрытые страницы ведут на вход сайта и возвращают обратно."""

    def test_login_required_redirects_to_site_login(self):
        response = self.client.get('/applications/318/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/accounts/login/?next=/applications/318/')

    def test_login_returns_to_next(self):
        User.objects.create_user('ivan', 'ivan@example.ru', 'pass-12345')
        response = self.client.post('/accounts/login/?next=/applications/318/',
                                    {'email': 'ivan@example.ru', 'password': 'pass-12345'})
        self.assertEqual(response['Location'], '/applications/318/')

    def test_login_ignores_external_next(self):
        User.objects.create_user('ivan', 'ivan@example.ru', 'pass-12345')
        response = self.client.post('/accounts/login/?next=https://evil.example/',
                                    {'email': 'ivan@example.ru', 'password': 'pass-12345'})
        self.assertEqual(response['Location'], '/accounts/profile/')


class TemplateUrlNamesTests(TestCase):
    def test_all_argless_url_tags_resolve(self):
        # регрессия: teams/verification_failed.html ссылался на несуществующий
        # 'teams:resend_verification' — просроченная ссылка подтверждения команды давала 500
        import re
        from pathlib import Path
        from django.conf import settings
        from django.urls import NoReverseMatch, reverse

        pattern = re.compile(r"{%\s*url\s+['\"]([\w:-]+)['\"]\s*%}")
        roots = ['templates', 'accounts/templates', 'teams/templates', 'organizers/templates',
                 'applications/templates', 'website/templates', 'demo/templates']
        bad = []
        for root in roots:
            for path in (Path(settings.BASE_DIR) / root).rglob('*.html'):
                for name in pattern.findall(path.read_text(encoding='utf-8', errors='replace')):
                    try:
                        reverse(name)
                    except NoReverseMatch:
                        bad.append(f'{path.relative_to(settings.BASE_DIR)}: {name}')
        self.assertEqual(bad, [])
