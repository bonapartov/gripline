"""Модели сайта по доменам.

Пакет сохраняет прежний импорт `website.models`: все имена реэкспортируются,
поэтому существующие импорты, миграции и Wagtail-регистрация не меняются.
"""
from .pages import *  # noqa: F401,F403
from .people import *  # noqa: F401,F403
from .equipment import *  # noqa: F401,F403
from .racing import *  # noqa: F401,F403
from .pages_content import *  # noqa: F401,F403
from .site_settings import *  # noqa: F401,F403
from .balance import *  # noqa: F401,F403
from .pages_extra import *  # noqa: F401,F403
from .content import *  # noqa: F401,F403
from .feedback import *  # noqa: F401,F403
from .dashboard import *  # noqa: F401,F403
from .app import *  # noqa: F401,F403

# Миграции ссылаются на эти функции по историческому пути website.models._*.
# Сохраняем его, хотя определения живут в доменных модулях.
from .equipment import _private_storage  # noqa: E402
from .feedback import (  # noqa: E402
    _feedback_attachment_path, _feedback_attachment_storage,
)

for _fn in (_private_storage, _feedback_attachment_storage,
            _feedback_attachment_path):
    _fn.__module__ = __name__
