from django.db import models

class TelegramUser(models.Model):
    """Хранение связи Telegram ID и email пользователя"""
    telegram_id = models.BigIntegerField(
        "Telegram ID",
        unique=True,
        help_text="ID пользователя в Telegram"
    )
    email = models.EmailField(
        "Email",
        help_text="Email, который пользователь указал при регистрации"
    )
    created_at = models.DateTimeField(
        "Дата привязки",
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        "Дата обновления",
        auto_now=True
    )

    def __str__(self):
        return f"{self.email} → {self.telegram_id}"

    class Meta:
        verbose_name = "Telegram пользователь"
        verbose_name_plural = "Telegram пользователи"
        indexes = [
            models.Index(fields=['telegram_id']),
            models.Index(fields=['email']),
        ]
