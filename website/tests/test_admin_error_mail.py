import logging
import sys

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings

from website.log import ThrottledAdminEmailHandler
from website.models import MailSettings


def _record(exc):
    try:
        raise exc
    except Exception:
        return logging.LogRecord('django.request', logging.ERROR, __file__, 1,
                                 'Internal Server Error: /x/', None, sys.exc_info())


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SERVER_EMAIL='Gripline <gripline.ru@yandex.ru>',
)
class ThrottledAdminEmailHandlerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.handler = ThrottledAdminEmailHandler()

    def test_error_goes_to_admin_notify_email_from_admin(self):
        MailSettings.objects.create(pk=1, admin_notify_email='ops@example.ru')
        self.handler.emit(_record(ValueError('boom')))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ops@example.ru'])
        self.assertIn('ValueError', mail.outbox[0].body)

    def test_default_recipient_is_working_mailbox(self):
        self.handler.emit(_record(ValueError('boom')))
        self.assertEqual(mail.outbox[0].to, ['gripline.ru@yandex.ru'])

    def test_same_error_sent_once_per_window(self):
        for _ in range(5):
            self.handler.emit(_record(ValueError('boom')))
        self.assertEqual(len(mail.outbox), 1)

    def test_hourly_limit_across_different_errors(self):
        for i in range(ThrottledAdminEmailHandler.HOURLY_LIMIT + 5):
            record = _record(ValueError(str(i)))
            record.exc_info = (type(f'E{i}', (Exception,), {}), record.exc_info[1], record.exc_info[2])
            self.handler.emit(record)
        self.assertEqual(len(mail.outbox), ThrottledAdminEmailHandler.HOURLY_LIMIT)
