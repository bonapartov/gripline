from .base import *
import os
from dotenv import load_dotenv

load_dotenv()

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False') == 'True'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY')

# Add your site's domain name(s) here.
ALLOWED_HOSTS = ['gripline.ru', 'www.gripline.ru', 'cleantogo.ru', 'www.admin.cleantogo.ru']

# Базовый URL сайта для ссылок в письмах (base.py содержит localhost-адрес для локальной разработки)
BASE_URL = 'https://gripline.ru'

# PostgreSQL Database (overrides base.py)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB'),
        'USER': os.getenv('POSTGRES_USER'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD'),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'),
        'OPTIONS': {
          'client_encoding': 'UTF8',
        },
    }
}

# Enable timezone support
USE_TZ = True
TIME_ZONE = 'Europe/Moscow'

# Email settings
DEFAULT_FROM_EMAIL = "Gripline <info@gripline.ru>"
ADMINS = [("Administrator", "admin@gripline.ru")]
MANAGERS = ADMINS
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Cache
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "cache",
        "KEY_PREFIX": "coderedcms",
        "TIMEOUT": 14400,
    }
}

# Static and media
STATIC_ROOT = BASE_DIR / "static"
MEDIA_ROOT = BASE_DIR / "media"

# Хешированные имена файлов (style.a1b2c3d4.css) — при каждом collectstatic
# меняется имя изменённого файла, значит меняется и URL в {% static %}.
# 30-дневный Cache-Control на /static/ (nginx) перестаёт быть риском отдать
# протухший JS/CSS: старый URL с прежним хешем просто больше никем не
# запрашивается после деплоя.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# Email SMTP settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.yandex.ru'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
EMAIL_HOST_USER = 'gripline.ru@yandex.ru'
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = 'Gripline <gripline.ru@yandex.ru>'
PASSWORD_RESET_TIMEOUT = 1800  # токен сброса пароля живёт 30 минут

# Security-настройки (найдено manage.py check --deploy при security-аудите,
# коммит 16d0b90). nginx уже терминирует TLS и редиректит весь HTTP на
# HTTPS (сервер-блок "managed by Certbot"), но Django этого не знает без
# SECURE_PROXY_SSL_HEADER — сам факт, что запрос до Django дошёл через
# proxy_pass по обычному HTTP, иначе читался бы как "небезопасный", и
# SECURE_SSL_REDIRECT=True зациклил бы редиректы (Django редиректит на
# https → nginx снова проксирует на Django по http → Django снова
# редиректит...). Оба параметра — только вместе, никогда по одному.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS — начинаем с часа, а не сразу с года: Django сам предупреждает, что
# опрометчиво выставленный SECURE_HSTS_SECONDS необратим (браузер запомнит
# политику и откажется ходить по HTTP на весь срок, даже если сертификат
# протухнет раньше). Через несколько недель стабильной работы можно поднять
# до стандартного года (31536000) и добавить SECURE_HSTS_INCLUDE_SUBDOMAINS.
SECURE_HSTS_SECONDS = 3600