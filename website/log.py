import time
import traceback

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.utils.log import AdminEmailHandler


class ThrottledAdminEmailHandler(AdminEmailHandler):
    """Письма о сбоях сайта с ограничителем.

    Отправка идёт с того же ящика, что и письма пользователям, а после взлома
    в сентябре 2026 Яндекс может снова урезать отправку при всплеске. Поэтому
    одна и та же ошибка приходит не чаще раза в DUPLICATE_WINDOW, а всего писем
    не больше HOURLY_LIMIT в час. Адресат — MailSettings.admin_notify_email
    (админка → Интеграции → Почта), а не settings.ADMINS.
    """

    DUPLICATE_WINDOW = 3600
    HOURLY_LIMIT = 10

    def emit(self, record):
        try:
            if not cache.add(f'admin-mail:dup:{self.fingerprint(record)}', 1, self.DUPLICATE_WINDOW):
                return
            bucket = f'admin-mail:count:{int(time.time() // 3600)}'
            cache.add(bucket, 0, 3600)
            if cache.incr(bucket) > self.HOURLY_LIMIT:
                return
        except Exception:
            pass  # кэш недоступен — лучше лишнее письмо, чем пропущенный сбой
        super().emit(record)

    @staticmethod
    def fingerprint(record):
        if record.exc_info and record.exc_info[1] is not None:
            exc_type, exc, tb = record.exc_info
            frame = traceback.extract_tb(tb)[-1] if tb else None
            where = f'{frame.filename}:{frame.lineno}' if frame else ''
            return f'{exc_type.__name__}:{where}'
        return f'{record.pathname}:{record.lineno}:{record.msg}'

    def send_mail(self, subject, message, *args, **kwargs):
        from website.mail import admin_notify_email

        mail = EmailMultiAlternatives(
            f'{settings.EMAIL_SUBJECT_PREFIX}{subject}', message, settings.SERVER_EMAIL,
            [admin_notify_email()], connection=self.connection(),
        )
        if kwargs.get('html_message'):
            mail.attach_alternative(kwargs['html_message'], 'text/html')
        mail.send(fail_silently=True)
