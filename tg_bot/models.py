from django.db import models
from django.contrib.auth.models import User
from website.models import Team, Driver

class TelegramUser(models.Model):
    """Связь пользователя Django с Telegram"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    telegram_id = models.BigIntegerField(unique=True, verbose_name="Telegram ID")
    username = models.CharField(max_length=255, blank=True, null=True)
    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    is_admin = models.BooleanField(default=False, verbose_name="Администратор")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"@{self.username or self.telegram_id}"

    class Meta:
        verbose_name = "Telegram пользователь"
        verbose_name_plural = "Telegram пользователи"

class PendingAction(models.Model):
    """Хранение временных данных для действий"""
    ACTION_TYPES = [
        ('team_approve', 'Подтверждение команды'),
        ('team_reject', 'Отклонение команды'),
        ('driver_approve', 'Подтверждение пилота'),
        ('driver_reject', 'Отклонение пилота'),
    ]

    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE)
    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    claim_id = models.PositiveIntegerField(verbose_name="ID заявки")
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "Ожидающее действие"
        verbose_name_plural = "Ожидающие действия"
