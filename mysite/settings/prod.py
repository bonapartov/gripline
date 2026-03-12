from .base import *  # noqa
import os

DEBUG = False

SECRET_KEY = os.getenv('@j607osv=gm8))*_9jx%tou(-ocwls13gr_ih8)a*@lhrl@5gb')

ALLOWED_HOSTS = ["gripline.ru", "www.gripline.ru"]

# База данных MySQL/MariaDB
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('DB_NAME', 'gripline'),
        'USER': os.getenv('DB_USER', 'gripline'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    }
}

DEFAULT_FROM_EMAIL = "Gripline <info@gripline.ru>"
ADMINS = [("Administrator", "admin@gripline.ru")]
MANAGERS = ADMINS
SERVER_EMAIL = DEFAULT_FROM_EMAIL

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "cache",  # noqa
        "KEY_PREFIX": "coderedcms",
        "TIMEOUT": 14400,
    }
}

STATIC_ROOT = BASE_DIR / "static"
MEDIA_ROOT = BASE_DIR / "media"
