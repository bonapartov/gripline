from .base import * # noqa

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "(tfrb^r^wdpjqrv61_=0pdlo8gzu!y5=7r8(tr_xq-nac2#14b"

# Разрешаем доступ по домену
ALLOWED_HOSTS = ["gripline.ru", "www.gripline.ru", "localhost", "127.0.0.1"]

# Настройки почты
DEFAULT_FROM_EMAIL = "Gripline Media <info@gripline.ru>"
SERVER_EMAIL = "info@gripline.ru"

ADMINS = [
    ("Vladimir", "vladimir@gripline.ru"), # Можешь поставить свою реальную почту
]

MANAGERS = ADMINS

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "cache",  # noqa
        "KEY_PREFIX": "coderedcms",
        "TIMEOUT": 14400,
    }
}
