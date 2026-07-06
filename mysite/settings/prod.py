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

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# Email SMTP settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.yandex.ru'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
EMAIL_HOST_USER = 'gripline.ru@yandex.ru'
EMAIL_HOST_PASSWORD = 'pcpdnxyjatnwuhud'
DEFAULT_FROM_EMAIL = 'Gripline <gripline.ru@yandex.ru>'
PASSWORD_RESET_TIMEOUT = 1800  # токен сброса пароля живёт 30 минут