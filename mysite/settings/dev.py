from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from .base import *


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "qdq2i*4v@%lq!qovq^jg!ovp!)*0)k*p=v178jv8w^m$njpb=)"

ALLOWED_HOSTS = ["*"]

WAGTAIL_CACHE = False

# Добавляем приложения

try:
    from .local import *
except ImportError:
    pass
