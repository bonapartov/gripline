from unittest.mock import patch

from django.test import TestCase, override_settings

from website.mail import (
    DBConfiguredEmailBackend,
    _ProxiedSMTP,
    _ProxiedSMTP_SSL,
    admin_notify_email,
    default_from_email,
)
from website.models import MailSettings


class DefaultFromEmailTests(TestCase):
    @override_settings(DEFAULT_FROM_EMAIL='Gripline <fallback@example.com>')
    def test_falls_back_to_settings_when_db_field_blank(self):
        self.assertEqual(default_from_email(), 'Gripline <fallback@example.com>')

    def test_uses_db_value_when_set(self):
        MailSettings.objects.create(pk=1, default_from_email='Gripline <new@example.com>')
        self.assertEqual(default_from_email(), 'Gripline <new@example.com>')


class AdminNotifyEmailTests(TestCase):
    def test_falls_back_to_hardcoded_default_when_db_field_blank(self):
        self.assertEqual(admin_notify_email(), 'gripline.ru@yandex.ru')

    def test_uses_db_value_when_set(self):
        MailSettings.objects.create(pk=1, admin_notify_email='ops@example.com')
        self.assertEqual(admin_notify_email(), 'ops@example.com')


class DBConfiguredEmailBackendTests(TestCase):
    """
    security-аудит / ТЗ gripline_tz_zaschita_pochty.md — компрометация ящика
    gripline.ru@yandex.ru. Кил-свитч (enabled=False) — единственная защита,
    которая должна работать мгновенно без деплоя, поэтому покрыта явно.
    """

    def test_enabled_false_drops_messages_without_sending(self):
        MailSettings.objects.create(pk=1, enabled=False)
        backend = DBConfiguredEmailBackend()
        sent = backend.send_messages(['не важно, до open() не дойдёт'])
        self.assertEqual(sent, 0)

    @override_settings(EMAIL_HOST_USER='fallback-user', EMAIL_HOST_PASSWORD='fallback-pass')
    def test_blank_db_credentials_fall_back_to_settings(self):
        # host/port/tls/ssl/timeout не поддерживают fallback — DB-авторитетны
        # всегда (не секреты, см. MailSettings docstring). Fallback есть только
        # у host_user/host_password/default_from_email (секреты/адрес).
        MailSettings.objects.create(pk=1, host_user='', host_password='', default_from_email='')
        backend = DBConfiguredEmailBackend()
        self.assertEqual(backend.username, 'fallback-user')
        self.assertEqual(backend.password, 'fallback-pass')

    def test_db_credentials_override_settings_when_set(self):
        MailSettings.objects.create(
            pk=1,
            host='smtp.example.com',
            port=2525,
            host_user='db-user@example.com',
            host_password='db-secret',
            use_tls=False,
            use_ssl=True,
        )
        backend = DBConfiguredEmailBackend()
        self.assertEqual(backend.host, 'smtp.example.com')
        self.assertEqual(backend.port, 2525)
        self.assertEqual(backend.username, 'db-user@example.com')
        self.assertEqual(backend.password, 'db-secret')
        self.assertFalse(backend.use_tls)
        self.assertTrue(backend.use_ssl)

    def test_singleton_row_created_on_demand_with_safe_defaults(self):
        self.assertEqual(MailSettings.objects.count(), 0)
        backend = DBConfiguredEmailBackend()
        self.assertEqual(MailSettings.objects.count(), 1)
        self.assertTrue(backend._mail_enabled)

    def test_connection_class_picks_proxied_smtp_variant_by_use_ssl(self):
        MailSettings.objects.create(pk=1, use_tls=True, use_ssl=False)
        self.assertIs(DBConfiguredEmailBackend().connection_class, _ProxiedSMTP)

        MailSettings.objects.filter(pk=1).update(use_tls=False, use_ssl=True)
        self.assertIs(DBConfiguredEmailBackend().connection_class, _ProxiedSMTP_SSL)


class ProxiedSmtpSocketTests(TestCase):
    """
    website/mail.py::_ProxiedSMTP(_SSL) — прод-хостинг блокирует прямой TCP
    на smtp.yandex.ru:587/465 (DPI-подобная блокировка, тот же паттерн, что
    у api.telegram.org — см. project_gripline_telegram_proxy). Без
    EMAIL_PROXY_URL поведение должно остаться прежним (прямое соединение).
    """

    @override_settings(EMAIL_PROXY_URL=None)
    def test_no_proxy_configured_falls_back_to_direct_connect(self):
        with patch('smtplib.SMTP._get_socket') as mocked:
            mocked.return_value = 'direct-socket'
            sock = _ProxiedSMTP()._get_socket('smtp.example.com', 587, 5)
        self.assertEqual(sock, 'direct-socket')
        mocked.assert_called_once_with('smtp.example.com', 587, 5)

    @override_settings(EMAIL_PROXY_URL='socks5h://127.0.0.1:10808')
    def test_proxy_configured_routes_through_socks(self):
        with patch('website.mail.socks.create_connection') as mocked:
            mocked.return_value = 'socks-socket'
            sock = _ProxiedSMTP()._get_socket('smtp.example.com', 587, 5)
        self.assertEqual(sock, 'socks-socket')
        _, kwargs = mocked.call_args
        self.assertEqual(mocked.call_args[0][0], ('smtp.example.com', 587))
        self.assertEqual(kwargs['proxy_addr'], '127.0.0.1')
        self.assertEqual(kwargs['proxy_port'], 10808)
