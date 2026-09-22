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

Прод-хостинг блокирует прямой исходящий TCP на smtp.yandex.ru:587/465 на
сетевом уровне (ICMP до IP проходит, TCP таймаутит — тот же DPI-паттерн, что
уже был с api.telegram.org, см. project_gripline_telegram_proxy в памяти и
website/telegram.py). Обнаружено 22.09.2026 при проверке новых SMTP-
credentials после ротации пароля приложения. Решение то же: локальный
SOCKS5-прокси Xray (127.0.0.1:10808, systemd-юнит xray.service, уже поднят
и настроен на прокси ЛЮБОГО исходящего трафика, не только Telegram — см.
routing-правила в /usr/local/etc/xray/config.json). settings.EMAIL_PROXY_URL
переиспользует тот же прокси-URL, что и TELEGRAM_PROXY_URL (одна и та же
переменная окружения на проде, см. ниже) — Django-бэкенд использует
smtplib напрямую (не requests), поэтому проксирование сделано через PySocks
(уже зависимость проекта — requirements.txt, используется для Telegram) на
уровне _get_socket(), а не через proxies= как в website/telegram.py.
"""
from urllib.parse import urlparse
from smtplib import SMTP, SMTP_SSL

import socks
from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend


def _proxy_url():
    return getattr(settings, 'EMAIL_PROXY_URL', None)


def _socks_connect(proxy_url, host, port, timeout):
    parsed = urlparse(proxy_url)
    return socks.create_connection(
        (host, port),
        timeout=timeout if timeout else None,
        proxy_type=socks.SOCKS5,
        proxy_addr=parsed.hostname,
        proxy_port=parsed.port,
        proxy_rdns=True,
    )


class _ProxiedSMTP(SMTP):
    """SMTP с TCP-соединением через SOCKS5, если settings.EMAIL_PROXY_URL задан
    (иначе — обычное прямое соединение, как раньше)."""

    def _get_socket(self, host, port, timeout):
        proxy_url = _proxy_url()
        if not proxy_url:
            return super()._get_socket(host, port, timeout)
        return _socks_connect(proxy_url, host, port, timeout)


class _ProxiedSMTP_SSL(SMTP_SSL):
    """Тот же прокси, но с TLS-оборачиванием сокета — повторяет логику
    stdlib SMTP_SSL._get_socket(), только raw-сокет идёт через SOCKS5."""

    def _get_socket(self, host, port, timeout):
        proxy_url = _proxy_url()
        if not proxy_url:
            return super()._get_socket(host, port, timeout)
        raw_socket = _socks_connect(proxy_url, host, port, timeout)
        return self.context.wrap_socket(raw_socket, server_hostname=self._host)


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

    @property
    def connection_class(self):
        return _ProxiedSMTP_SSL if self.use_ssl else _ProxiedSMTP

    def send_messages(self, email_messages):
        if not self._mail_enabled:
            return 0
        return super().send_messages(email_messages)
