"""
Точка расширения: автоответы на частые вопросы (ТЗ, «Потом»).

Ядро вызывает провайдер перед созданием обращения. Сейчас подключена
заглушка NullAutoReply (ничего не находит). Модель правил автоответов
намеренно не создаётся — появится вместе с реальным провайдером.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class AutoReply:
    text: str
    # создавать ли обращение после автоответа (по умолчанию — нет)
    still_create_feedback: bool = False


class AutoReplyProvider:
    def match(self, draft) -> Optional[AutoReply]:
        raise NotImplementedError


class NullAutoReply(AutoReplyProvider):
    def match(self, draft) -> Optional[AutoReply]:
        return None


_provider: AutoReplyProvider = NullAutoReply()


def get_provider() -> AutoReplyProvider:
    return _provider


def set_provider(provider: AutoReplyProvider) -> None:
    global _provider
    _provider = provider
