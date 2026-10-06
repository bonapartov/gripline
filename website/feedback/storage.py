"""Закрытое хранилище вложений обращений (вне публичного MEDIA_ROOT)."""
import os
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils import timezone


class PrivateStorage(FileSystemStorage):
    """У файлов нет публичного URL (FileSystemStorage с base_url=None
    подставил бы MEDIA_URL — вводящую в заблуждение ссылку). Отдача — только
    через админ-вьюху с проверкой прав."""

    def url(self, name):
        raise ValueError('Вложения обращений не имеют публичного URL')


def private_storage():
    return PrivateStorage(location=str(settings.PRIVATE_MEDIA_ROOT))


def attachment_upload_path(instance, filename):
    """feedback/YYYY/MM/<uuid>.<ext> — имя генерируется, оригинал хранится в БД."""
    ext = os.path.splitext(filename)[1].lower()
    now = timezone.now()
    return f'feedback/{now:%Y}/{now:%m}/{uuid.uuid4().hex}{ext}'
