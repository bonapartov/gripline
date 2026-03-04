from django.db import models
from django.contrib.auth.models import User
from website.models import Team, Driver
from wagtail.snippets.models import register_snippet
from django.utils import timezone

class TeamManager(models.Model):
    """Кто управляет командой (капитан, менеджер)"""
    ROLE_CHOICES = [
        ('captain', 'Капитан'),
        ('manager', 'Менеджер'),
        ('media', 'Медиа-менеджер'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_managers')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='managers')
    role = models.CharField("Роль", max_length=20, choices=ROLE_CHOICES, default='manager')
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Дата назначения", auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.team.name} ({self.get_role_display()})"

    class Meta:
        verbose_name = "Управляющий командой"
        verbose_name_plural = "Управляющие командами"
        unique_together = ['user', 'team']  # Один пользователь может управлять командой один раз


class TeamClaim(models.Model):
    """Заявка на управление командой"""
    STATUS_CHOICES = [
        ('pending', 'Ожидает подтверждения'),
        ('approved', 'Подтверждено'),
        ('rejected', 'Отклонено'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Пользователь")
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Выбранная команда"
    )
    requested_team_name = models.CharField("Запрошенное название команды", max_length=255)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_comment = models.TextField("Комментарий администратора", blank=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_team_claims',
        verbose_name="Проверил"
    )
    reviewed_at = models.DateTimeField("Дата проверки", null=True, blank=True)

    def __str__(self):
        return f"{self.requested_team_name} - {self.get_status_display()}"

    class Meta:
        verbose_name = "Заявка команды"
        verbose_name_plural = "Заявки команд"


class TeamJoinRequest(models.Model):
    """Заявка пилота на вступление в команду"""
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('approved', 'Принята'),
        ('rejected', 'Отклонена'),
    ]

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, verbose_name="Пилот")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, verbose_name="Команда")
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default='pending')
    comment = models.TextField("Комментарий пилота", blank=True, help_text="Почему хочет в команду")
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_join_requests',
        verbose_name="Рассмотрел"
    )
    reviewed_at = models.DateTimeField("Дата рассмотрения", null=True, blank=True)

    def __str__(self):
        return f"{self.driver.full_name} -> {self.team.name}"

    class Meta:
        verbose_name = "Заявка на вступление"
        verbose_name_plural = "Заявки на вступление"
        unique_together = ['driver', 'team']  # Чтобы не спамили
