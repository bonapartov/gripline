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
