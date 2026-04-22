from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from website.models import Driver

class UserProfile(models.Model):
    """Расширение стандартной модели User"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Привязанный пилот"
    )
    city = models.CharField("Город", max_length=100, blank=True)
    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.driver}"

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    telegram_id = models.BigIntegerField(
        "Telegram ID",
        null=True,
        blank=True,
        unique=True,
        help_text="ID для отправки уведомлений в Telegram. Привязывается через бота."
    )
    telegram_notifications = models.BooleanField(
        "Уведомления в Telegram",
        default=False,
        help_text="Отправлять уведомления о статусе заявок в Telegram"
    )


class DriverClaim(models.Model):
    """Заявка на привязку к пилоту"""
    STATUS_CHOICES = [
        ('pending', 'Ожидает подтверждения'),
        ('approved', 'Подтверждено'),
        ('rejected', 'Отклонено'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Пользователь")
    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Выбранный пилот"
    )
    requested_first_name = models.CharField("Запрошенное имя", max_length=100)
    requested_last_name = models.CharField("Запрошенная фамилия", max_length=100)
    requested_city = models.CharField("Запрошенный город", max_length=100, blank=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_comment = models.TextField("Комментарий администратора", blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_claims',
        verbose_name="Проверил"
    )
    reviewed_at = models.DateTimeField("Дата проверки", null=True, blank=True)

    def __str__(self):
        return f"{self.requested_first_name} {self.requested_last_name} - {self.get_status_display()}"

    class Meta:
        verbose_name = "Заявка пилота"
        verbose_name_plural = "Заявки пилотов"
        ordering = ['-created_at']
