"""
Настройки исходящей почты вынесены в Wagtail admin → Интеграции → Почта
(MailSettings, website/models.py) — см. ТЗ gripline_tz_zaschita_pochty.md
(компрометация ящика gripline.ru@yandex.ru спам-рассылкой, сентябрь 2026).

DBConfiguredEmailBackend читает MailSettings.get() при КАЖДОЙ отправке
письма (не один раз при старте процесса) — правка в админке действует
мгновенно, без рестарта gunicorn. Пустое текстовое поле в админке = fallback
на settings.EMAIL_HOST_USER/EMAIL_HOST_PASSWORD/DEFAULT_FROM_EMAIL
(переменные окружения) — деплой этого модуля сам по себе не меняет
поведение прода, пока админ не заполнит поле.

enabled=False — кил-свитч: письма молча не уходят (send_messages
возвращает 0, ни одного исключения наружу) — на случай повторной
компрометации ящика, чтобы не ждать деплоя.
"""
from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend


def _mail_settings():
    from .models import MailSettings
    return MailSettings.get()


def default_from_email():
    """Адрес отправителя (From) — переопределяется в админке, иначе settings.DEFAULT_FROM_EMAIL."""
    return _mail_settings().default_from_email or settings.DEFAULT_FROM_EMAIL


def admin_notify_email():
    """Куда падают уведомления администратору о новых заявках — не адрес отправителя."""
    return _mail_settings().admin_notify_email or 'gripline.ru@yandex.ru'


class DBConfiguredEmailBackend(SMTPEmailBackend):
    def __init__(self, *args, **kwargs):
        cfg = _mail_settings()
        self._mail_enabled = cfg.enabled
        kwargs.setdefault('host', cfg.host or None)
        kwargs.setdefault('port', cfg.port or None)
        kwargs.setdefault('username', cfg.host_user or None)
        kwargs.setdefault('password', cfg.host_password or None)
        kwargs.setdefault('use_tls', cfg.use_tls)
        kwargs.setdefault('use_ssl', cfg.use_ssl)
        kwargs.setdefault('timeout', cfg.timeout or None)
        super().__init__(*args, **kwargs)

    def send_messages(self, email_messages):
        if not self._mail_enabled:
            return 0
        return super().send_messages(email_messages)
