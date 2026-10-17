from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField
from website.models import Driver, Team
from wagtail.contrib.settings.models import BaseGenericSetting
from wagtail.admin.panels import FieldPanel
from wagtail.contrib.settings.registry import register_setting

from applications import document_kinds

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
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Команда",
    )
    roles = ArrayField(
        models.CharField(max_length=20),
        default=list,
        blank=True,
        verbose_name="Роли",
        help_text="Автоматически. Возможные значения: pilot, manager",
    )
    verified = models.BooleanField(
        "Верифицирован администратором",
        default=False,
        help_text="Администратор подтвердил привязку к пилоту",
    )
    city = models.CharField("Город", max_length=100, blank=True)
    email_verified = models.BooleanField(
        "Email подтверждён", default=True,
        help_text="False — только у новых регистраций по email до перехода по ссылке из письма. "
                  "Не связано с is_active: is_active=False значит «заблокирован», и ссылка из письма его не снимает.",
    )
    pending_team_name = models.CharField(
        "Название команды из регистрации", max_length=255, blank=True,
        help_text="Хранится до подтверждения email и выбора команды; нужно, чтобы ссылку можно было открыть в другом браузере.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.driver}"

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    # Не уникален: родитель подключает свой Telegram в аккаунтах нескольких детей.
    telegram_id = models.BigIntegerField(
        "Telegram ID",
        null=True,
        blank=True,
        db_index=True,
        help_text="ID для отправки уведомлений в Telegram. Привязывается кнопкой в ЛК через бота."
    )
    telegram_notifications = models.BooleanField(
        "Уведомления в Telegram",
        default=False,
        help_text="Отправлять уведомления о статусе заявок в Telegram"
    )
    # Одноразовый код ссылки t.me/<бот>?start=link-<код> (кнопка «Подключить Telegram» в ЛК).
    telegram_link_token = models.CharField(max_length=64, blank=True, db_index=True)
    telegram_link_created_at = models.DateTimeField(null=True, blank=True)

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

    birth_date_public = models.BooleanField(
        "Публиковать дату рождения",
        default=False,
        help_text="Показывать дату рождения в публичной карточке пилота на сайте"
    )

    @property
    def is_minor(self):
        if not self.birth_date:
            return False
        from datetime import date
        return (date.today() - self.birth_date).days / 365.25 < 18


@register_setting
class SocialAuthSettings(BaseGenericSetting):
    yandex_enabled = models.BooleanField("Вход через Яндекс", default=False)
    yandex_client_id = models.CharField("Яндекс Client ID", max_length=200, blank=True)
    yandex_client_secret = models.CharField("Яндекс Client Secret", max_length=200, blank=True)
    vk_enabled = models.BooleanField("Вход через ВКонтакте", default=False)
    vk_client_id = models.CharField("VK Client ID", max_length=200, blank=True)
    vk_client_secret = models.CharField("VK Client Secret", max_length=200, blank=True)
    google_enabled = models.BooleanField("Вход через Google", default=False)

    contact_email = models.EmailField(
        "Контактный email",
        blank=True,
        help_text="Email для связи с администратором (показывается пользователям)"
    )
    telegram_contact = models.CharField(
        "Telegram администратора",
        max_length=100,
        blank=True,
        help_text="Telegram-аккаунт или канал, например @gripline"
    )

    panels = [
        FieldPanel('yandex_enabled'),
        FieldPanel('yandex_client_id'),
        FieldPanel('yandex_client_secret'),
        FieldPanel('vk_enabled'),
        FieldPanel('vk_client_id'),
        FieldPanel('vk_client_secret'),
        FieldPanel('google_enabled'),
        FieldPanel('contact_email'),
        FieldPanel('telegram_contact'),
    ]

    class Meta:
        verbose_name = "Авторизация на сайте"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class PilotDocument(models.Model):
    """Личное хранилище документов пилота (паспорт, лицензия и т.д.).

    Обычно привязан к профилю. Документ, который менеджер команды загрузил за пилота без
    подтверждённого аккаунта, хранится у пилота (driver, profile пустой) и переходит в его ЛК,
    когда аккаунт подтвердят (applications.vault.attach_held_documents) — до этого его не видит
    никто, кроме команды через её заявки: неподтверждённый аккаунт мог завести кто угодно."""
    profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, null=True, blank=True,
        related_name='documents', verbose_name='Профиль'
    )
    driver = models.ForeignKey(
        'website.Driver', on_delete=models.CASCADE, null=True, blank=True,
        related_name='held_documents', verbose_name='Пилот (до подтверждения аккаунта)'
    )
    kind = models.CharField('Тип', max_length=30, choices=document_kinds.VAULT_CHOICES,
                            default=document_kinds.OTHER, db_index=True)
    name = models.CharField('Название документа', max_length=200)
    doc_number = models.CharField('Номер документа', max_length=100, blank=True)
    file = models.FileField('Файл', upload_to='pilot_documents/')
    expiry_date = models.DateField('Срок действия', null=True, blank=True)
    uploaded_at = models.DateTimeField('Загружен', auto_now_add=True)
    # Организатор отклонил этот файл в заявке — в новые заявки он сам не подставляется,
    # пока пилот не загрузит другой.
    rejected_at = models.DateTimeField('Отклонён организатором', null=True, blank=True)
    rejected_comment = models.TextField('Причина отклонения', blank=True)
    # Медсправка: согласие на обработку сведений о здоровье (applications/health_consent.py).
    health_consent_at = models.DateTimeField('Согласие на сведения о здоровье', null=True, blank=True)
    health_consent_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        verbose_name='Согласие отметил',
    )

    class Meta:
        verbose_name = 'Документ пилота'
        verbose_name_plural = 'Документы пилота'
        ordering = ['name']
        constraints = [models.CheckConstraint(
            condition=models.Q(profile__isnull=False) | models.Q(driver__isnull=False),
            name='pilotdocument_has_owner')]

    def __str__(self):
        return f"{self.profile or self.driver} — {self.name}"

    @property
    def is_expired(self):
        if not self.expiry_date:
            return False
        from datetime import date
        return date.today() > self.expiry_date

    @property
    def expires_soon(self):
        if not self.expiry_date:
            return False
        from datetime import date
        delta = (self.expiry_date - date.today()).days
        return 0 <= delta <= 30

    @property
    def days_left(self):
        if not self.expiry_date:
            return None
        from datetime import date
        return (self.expiry_date - date.today()).days

    def valid_through(self, day):
        """Годится для этапа, который идёт до `day` включительно."""
        return self.rejected_at is None and (self.expiry_date is None or self.expiry_date >= day)


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


class PushToken(models.Model):
    """Push-токен устройства для FCM-уведомлений."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_tokens', verbose_name="Пользователь")
    token = models.CharField("Токен", max_length=255, unique=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} — {self.token[:20]}…"

    class Meta:
        verbose_name = "Push-токен"
        verbose_name_plural = "Push-токены"
