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

    # Личные данные пилота для автозаполнения заявок
    middle_name = models.CharField("Отчество", max_length=100, blank=True)
    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    citizenship = models.CharField("Гражданство", max_length=100, blank=True, default="Россия")
    phone = models.CharField("Телефон", max_length=30, blank=True)
    license_number = models.CharField("Лицензия пилота", max_length=100, blank=True)
    sport_rank = models.CharField("Спортивное звание", max_length=100, blank=True)

    # Данные родителя/опекуна (для несовершеннолетних)
    parent_last_name = models.CharField("Фамилия родителя", max_length=100, blank=True)
    parent_first_name = models.CharField("Имя родителя", max_length=100, blank=True)
    parent_middle_name = models.CharField("Отчество родителя", max_length=100, blank=True)
    parent_relation = models.CharField(
        "Кем приходится", max_length=20, blank=True,
        choices=[('mother', 'Мать'), ('father', 'Отец'), ('guardian', 'Опекун/попечитель')]
    )
    parent_phone = models.CharField("Телефон родителя", max_length=30, blank=True)
    parent_email = models.EmailField("Email родителя", blank=True)

    # Данные карта по умолчанию
    default_chassis_brand = models.CharField("Марка шасси", max_length=100, blank=True)
    default_engine = models.CharField("Двигатель", max_length=100, blank=True)
    default_transponder = models.CharField("Номер транспондера AMB", max_length=50, blank=True)

    @property
    def is_minor(self):
        if not self.birth_date:
            return False
        from datetime import date
        return (date.today() - self.birth_date).days / 365.25 < 18


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
