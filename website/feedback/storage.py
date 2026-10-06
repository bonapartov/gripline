"""Закрытое хранилище вложений обращений (вне публичного MEDIA_ROOT)."""
import os
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils import timezone


def private_storage():
    # base_url=None — у файла нет публичного URL; отдача только через
    # админ-вьюху с проверкой прав.
    return FileSystemStorage(location=str(settings.PRIVATE_MEDIA_ROOT), base_url=None)


def attachment_upload_path(instance, filename):
    """feedback/YYYY/MM/<uuid>.<ext> — имя генерируется, оригинал хранится в БД."""
    ext = os.path.splitext(filename)[1].lower()
    now = timezone.now()
    return f'feedback/{now:%Y}/{now:%m}/{uuid.uuid4().hex}{ext}'
