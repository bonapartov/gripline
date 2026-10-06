"""
Интерфейс канала связи. Ядро (website/feedback/service.py) знает только
его — ничего про Telegram. Второй канал (MAX, VK) = ещё один адаптер.
"""
from abc import ABC, abstractmethod
from typing import Optional, Sequence


class DeliveryError(Exception):
    """Сообщение не доставлено (пользователь заблокировал бота и т.п.)."""


class ChannelAdapter(ABC):
    channel = ''

    @abstractmethod
    async def send_message(self, user, text: str, buttons: Optional[Sequence] = None) -> Optional[int]:
        """Отправить сообщение пользователю. buttons — строки кнопок
        [[(подпись, callback_data), ...], ...]. Вернуть id сообщения;
        при недоставке — DeliveryError."""

    @abstractmethod
    async def send_to_admin(self, feedback) -> tuple[Optional[int], Optional[int]]:
        """Отправить карточку обращения модераторам.
        Вернуть (id сообщения, id темы/треда)."""

    @abstractmethod
    async def update_admin_card(self, feedback) -> None:
        """Перерисовать карточку (статус, кнопки, анонимизация)."""

    @abstractmethod
    async def download_attachment(self, ref) -> bytes:
        """Скачать вложение по ссылке канала (file_id и т.п.)."""
