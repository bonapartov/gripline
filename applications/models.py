from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, timedelta

from . import document_kinds

# Сколько черновик держит стартовый номер и место в лимите после последнего сохранения шага.
# Брошенный черновик не удаляется: вернувшись, человек продолжит, если номер ещё свободен.
DRAFT_HOLD = timedelta(hours=12)


class TeamStageEntry(models.Model):
    """Заявка команды на этап: менеджер заявляет несколько пилотов (в т.ч. в разных классах)
    одним пакетом. Каждый пилот — обычная Application(submitted_by_type='team') со ссылкой
    сюда, поэтому номера, лимит мест, документы, УТС и экраны организатора работают как у
    одиночной заявки. Мастер — applications/team_wizard.py."""

    STATUS_CHOICES = [('draft', 'Черновик'), ('submitted', 'Отправлена')]
    PAYMENT_SINGLE, PAYMENT_PER_PILOT = 'single', 'per_pilot'
    PAYMENT_CHOICES = [(PAYMENT_PER_PILOT, 'Отдельно за каждого пилота'),
                       (PAYMENT_SINGLE, 'Одной квитанцией за всю команду')]

    stage = models.ForeignKey('organizers.Stage', on_delete=models.CASCADE, related_name='team_entries')
    team = models.ForeignKey('website.Team', on_delete=models.CASCADE, related_name='stage_entries',
                             verbose_name='Команда')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_stage_entries',
                                   verbose_name='Менеджер')
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='draft')
    payment_mode = models.CharField('Оплата', max_length=20, choices=PAYMENT_CHOICES, default=PAYMENT_PER_PILOT)
    rep_last_name = models.CharField('Фамилия представителя', max_length=100, blank=True)
    rep_first_name = models.CharField('Имя представителя', max_length=100, blank=True)
    rep_phone = models.CharField('Телефон представителя', max_length=30, blank=True)
    rep_email = models.EmailField('Email представителя', blank=True)
    # Режим «одной квитанцией»: файл копируется ссылкой в платежи всех отправленных заявок пакета,
    # которые ещё ждут квитанцию; организатор подтверждает оплату по каждой заявке, как обычно.
    receipt_file = models.FileField('Квитанция за команду', upload_to='payment_receipts/%Y/%m/',
                                    blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField('Отправлена', null=True, blank=True)

    class Meta:
        verbose_name = 'Заявка команды на этап'
        verbose_name_plural = 'Заявки команд на этапы'
        ordering = ['-created_at']
        # Одна на команду и этап: пилотов добавляют в неё же, в т.ч. после отправки первых.
        unique_together = [('stage', 'team')]

    def __str__(self):
        return f'{self.team} — {self.stage}'

    def active_applications(self):
        return self.applications.exclude(status__in=('rejected', 'cancelled'))


class Application(models.Model):
    """Заявка на участие в этапе — универсальная, подаётся пилотом, командой или организатором"""

    SUBMITTED_BY_CHOICES = [
        ('pilot', 'Пилот'),
        ('team', 'Команда'),
        ('organizer', 'Организатор'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Черновик'),
        ('submitted', 'Подана'),
        ('confirmed', 'Подтверждена'),
        ('rejected', 'Отклонена'),
        ('cancelled', 'Отозвана'),
    ]

    PARTICIPATION_RACE = 'race'
    PARTICIPATION_TRAINING_RACE = 'training_race'
    PARTICIPATION_TRAINING = 'training'
    PARTICIPATION_CHOICES = [
        (PARTICIPATION_RACE, 'Только этап'),
        (PARTICIPATION_TRAINING_RACE, 'УТС + этап'),
        (PARTICIPATION_TRAINING, 'Только УТС'),
    ]

    stage = models.ForeignKey(
        'organizers.Stage', on_delete=models.CASCADE, related_name='applications'
    )
    participation = models.CharField(
        'Участие', max_length=20, choices=PARTICIPATION_CHOICES, default=PARTICIPATION_RACE,
    )
    submitted_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='submitted_applications'
    )
    submitted_by_type = models.CharField(
        max_length=20, choices=SUBMITTED_BY_CHOICES, default='pilot'
    )
    team_entry = models.ForeignKey(
        TeamStageEntry, on_delete=models.CASCADE, null=True, blank=True, related_name='applications',
        verbose_name='Заявка команды',
    )
    race_class = models.ForeignKey(
        'website.RaceClass', on_delete=models.SET_NULL, null=True, blank=True
    )
    start_number = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    organizer_comment = models.TextField(blank=True)
    entry_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    # Мастер подачи: последний пройденный шаг черновика (0 — ничего не пройдено).
    wizard_step = models.PositiveSmallIntegerField('Пройдено шагов мастера', default=0)
    withdrawn_at = models.DateTimeField('Отозвана', null=True, blank=True)
    withdraw_reason = models.TextField('Причина отзыва', blank=True)

    class Meta:
        verbose_name = 'Заявка'
        verbose_name_plural = 'Заявки'
        ordering = ['-created_at']

    def __str__(self):
        try:
            pilot_name = self.pilot.full_name
        except Exception:
            pilot_name = self.submitted_by.email
        return f"{pilot_name} — {self.stage}"

    def get_total_amount(self):
        options_total = sum(o.price_at_time for o in self.selected_options.all())
        return self.entry_fee_amount + options_total

    @staticmethod
    def holding_q():
        """Заявки, которые держат номер и место: поданные и подтверждённые, а черновики —
        только DRAFT_HOLD после последнего сохранения."""
        return (Q(status__in=('submitted', 'confirmed'))
                | Q(status='draft', updated_at__gte=timezone.now() - DRAFT_HOLD))

    def is_number_reserved(self):
        if self.status == 'draft':
            return self.updated_at is None or self.updated_at >= timezone.now() - DRAFT_HOLD
        return self.status in ('submitted', 'confirmed')


class ApplicationApplicant(models.Model):
    """Заявитель — команда или физическое лицо"""

    TYPE_CHOICES = [
        ('team', 'Команда'),
        ('individual', 'Физическое лицо'),
    ]

    application = models.OneToOneField(
        Application, on_delete=models.CASCADE, related_name='applicant'
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='individual')
    team = models.ForeignKey(
        'website.Team', on_delete=models.SET_NULL, null=True, blank=True
    )
    name = models.CharField(max_length=255, blank=True, verbose_name='Название/ФИО')
    license_number = models.CharField(max_length=100, blank=True, verbose_name='Номер лицензии')
    contract_number = models.CharField(max_length=100, blank=True, verbose_name='№ договора')
    contract_date = models.DateField(null=True, blank=True, verbose_name='Дата договора')
    rep_first_name = models.CharField(max_length=100, blank=True, verbose_name='Имя представителя')
    rep_last_name = models.CharField(max_length=100, blank=True, verbose_name='Фамилия представителя')
    rep_email = models.EmailField(blank=True, verbose_name='Email представителя')
    rep_phone = models.CharField(max_length=30, blank=True, verbose_name='Телефон представителя')
    # Команды нет в списке: вписана вручную, при отправке заявки создаётся TeamClaim на
    # контакт (после одобрения он — менеджер), а при одобрении заявитель привязывается к Team.
    new_team_city = models.CharField(max_length=100, blank=True, verbose_name='Город новой команды')
    new_team_email = models.EmailField(blank=True, verbose_name='Email контакта новой команды')
    team_claim = models.ForeignKey(
        'teams.TeamClaim', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='applicants', verbose_name='Заявка на новую команду',
    )

    class Meta:
        verbose_name = 'Заявитель'

    def __str__(self):
        return self.name or self.rep_last_name


class ApplicationPilot(models.Model):
    """Пилот в заявке — синхронизируется с Driver профилем"""

    PARENT_RELATION_CHOICES = [
        ('mother', 'Мать'),
        ('father', 'Отец'),
        ('guardian', 'Опекун/попечитель'),
    ]

    application = models.OneToOneField(
        Application, on_delete=models.CASCADE, related_name='pilot'
    )
    driver = models.ForeignKey(
        'website.Driver', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='applications'
    )
    # Пилот без подтверждённого профиля: при отправке заявки создаётся DriverClaim (на
    # выбранного из базы «это я» или на нового пилота); при одобрении заполняется driver.
    requested_driver = models.ForeignKey(
        'website.Driver', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Пилот из базы (на подтверждении)',
    )
    driver_claim = models.ForeignKey(
        'accounts.DriverClaim', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='application_pilots', verbose_name='Заявка на профиль пилота',
    )

    # Личные данные
    first_name = models.CharField(max_length=100, verbose_name='Имя')
    last_name = models.CharField(max_length=100, verbose_name='Фамилия')
    middle_name = models.CharField(max_length=100, blank=True, verbose_name='Отчество')
    citizenship = models.CharField(max_length=100, default='Россия', verbose_name='Гражданство')
    birth_date = models.DateField(null=True, blank=True, verbose_name='Дата рождения')
    sport_rank = models.CharField(max_length=100, blank=True, verbose_name='Спортивное звание')
    license_number = models.CharField(max_length=100, blank=True, verbose_name='Лицензия пилота')

    # Контакты
    email = models.EmailField(blank=True, verbose_name='Email')
    phone = models.CharField(max_length=30, blank=True, verbose_name='Телефон')
    city = models.CharField(max_length=100, blank=True, verbose_name='Город')
    country = models.CharField(max_length=100, default='Россия', verbose_name='Страна')

    # Родитель/опекун (для несовершеннолетних)
    parent_last_name = models.CharField(max_length=100, blank=True, verbose_name='Фамилия родителя')
    parent_first_name = models.CharField(max_length=100, blank=True, verbose_name='Имя родителя')
    parent_middle_name = models.CharField(max_length=100, blank=True, verbose_name='Отчество родителя')
    parent_relation = models.CharField(
        max_length=20, blank=True, choices=PARENT_RELATION_CHOICES, verbose_name='Кем приходится'
    )
    parent_phone = models.CharField(max_length=30, blank=True, verbose_name='Телефон родителя')
    parent_email = models.EmailField(blank=True, verbose_name='Email родителя')

    class Meta:
        verbose_name = 'Пилот в заявке'

    @property
    def full_name(self):
        parts = [self.last_name, self.first_name, self.middle_name]
        return ' '.join(p for p in parts if p)

    @property
    def is_minor(self):
        if not self.birth_date:
            return False
        age = (date.today() - self.birth_date).days / 365.25
        return age < 18

    def __str__(self):
        return self.full_name


class ApplicationKart(models.Model):
    """Карт, заявленный в заявке"""

    application = models.OneToOneField(
        Application, on_delete=models.CASCADE, related_name='kart'
    )
    chassis_brand = models.CharField(max_length=100, verbose_name='Марка шасси')
    engine_1 = models.CharField(max_length=100, verbose_name='Двигатель 1')
    engine_2 = models.CharField(max_length=100, blank=True, verbose_name='Двигатель 2')
    tires = models.CharField(max_length=100, blank=True, verbose_name='Шины')
    transponder_number = models.CharField(max_length=50, blank=True, verbose_name='Номер транспондера AMB')
    ad_consent = models.BooleanField(default=True, verbose_name='Согласие на размещение рекламы')

    class Meta:
        verbose_name = 'Карт в заявке'

    def __str__(self):
        return f"{self.chassis_brand} / {self.engine_1}"


class ApplicationMechanic(models.Model):
    """Механик (необязательный)"""

    application = models.OneToOneField(
        Application, on_delete=models.CASCADE, related_name='mechanic'
    )
    last_name = models.CharField(max_length=100, verbose_name='Фамилия')
    first_name = models.CharField(max_length=100, verbose_name='Имя')
    middle_name = models.CharField(max_length=100, blank=True, verbose_name='Отчество')
    license_number = models.CharField(max_length=100, blank=True, verbose_name='Лицензия механика')
    phone = models.CharField(max_length=30, blank=True, verbose_name='Телефон')
    email = models.EmailField(blank=True, verbose_name='Email')

    class Meta:
        verbose_name = 'Механик в заявке'

    @property
    def full_name(self):
        parts = [self.last_name, self.first_name, self.middle_name]
        return ' '.join(p for p in parts if p)

    def __str__(self):
        return self.full_name


class ApplicationAchievement(models.Model):
    """Достижения пилота — до 6 позиций"""

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='achievements'
    )
    competition_name = models.CharField(max_length=255, verbose_name='Соревнование')
    year = models.PositiveIntegerField(verbose_name='Год')
    achievement = models.CharField(max_length=255, verbose_name='Достижение')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        verbose_name = 'Достижение пилота'


# ---------------------------------------------------------------------------
# Настройки этапа
# ---------------------------------------------------------------------------

class StageDocument(models.Model):
    """Документ, требуемый для участия — настраивается организатором для каждого этапа"""

    stage = models.ForeignKey(
        'organizers.Stage', on_delete=models.CASCADE, related_name='required_documents'
    )
    kind = models.CharField('Тип', max_length=30, choices=document_kinds.CHOICES,
                            default=document_kinds.OTHER)
    name = models.CharField(max_length=255, verbose_name='Название документа')
    description = models.TextField(blank=True, verbose_name='Пояснение')
    required = models.BooleanField(default=True, verbose_name='Обязательный')
    minors_only = models.BooleanField(
        default=False, verbose_name='Только для несовершеннолетних'
    )
    has_expiry_date = models.BooleanField(
        default=False, verbose_name='Есть срок действия'
    )
    # Снятый с этапа документ, по которому уже есть загрузки, не удаляется
    # (каскад унёс бы файлы участников), а выключается.
    is_active = models.BooleanField(default=True, verbose_name='Запрашивается')
    source = models.ForeignKey(
        'ChampionshipDocument', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stage_copies', verbose_name='Документ чемпионата',
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        verbose_name = 'Требуемый документ'
        verbose_name_plural = 'Требуемые документы'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        document_kinds.apply_fixed(self)
        super().save(*args, **kwargs)

    @property
    def is_fixed_kind(self):
        return document_kinds.is_fixed(self.kind)


class ApplicationDocument(models.Model):
    """Загруженный документ по заявке"""

    STATUS_CHOICES = [
        ('pending', 'Ожидает загрузки'),
        ('uploaded', 'Загружен'),
        ('verified', 'Проверен ✓'),
        ('rejected', 'Отклонён ✗'),
    ]

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='documents'
    )
    stage_document = models.ForeignKey(
        StageDocument, on_delete=models.CASCADE, related_name='submitted'
    )
    file = models.FileField(
        upload_to='application_docs/%Y/%m/', blank=True, null=True,
        verbose_name='Файл'
    )
    expiry_date = models.DateField(null=True, blank=True, verbose_name='Срок действия')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending'
    )
    # Документ ЛК пилота, откуда подставлен файл или куда он сохранён при загрузке.
    # Отклонение организатором помечает его, чтобы он больше не подставлялся сам.
    vault_document = models.ForeignKey(
        'accounts.PilotDocument', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='application_documents', verbose_name='Документ из ЛК',
    )
    organizer_comment = models.TextField(blank=True, verbose_name='Комментарий организатора')
    uploaded_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_documents'
    )

    class Meta:
        verbose_name = 'Документ заявки'

    @property
    def is_expired(self):
        if self.expiry_date:
            return self.expiry_date < date.today()
        return False

    def __str__(self):
        return f"{self.stage_document.name} — {self.get_status_display()}"


class ChampionshipDocument(models.Model):
    """Шаблонный документ чемпионата — копируется в этапы при registration_mode='all'"""
    championship = models.ForeignKey(
        'organizers.Championship', on_delete=models.CASCADE, related_name='championship_documents'
    )
    kind = models.CharField('Тип', max_length=30, choices=document_kinds.CHOICES,
                            default=document_kinds.OTHER)
    name = models.CharField(max_length=255, verbose_name='Название документа')
    description = models.TextField(blank=True, verbose_name='Пояснение')
    required = models.BooleanField(default=True, verbose_name='Обязательный')
    minors_only = models.BooleanField(default=False, verbose_name='Только для несовершеннолетних')
    has_expiry_date = models.BooleanField(default=False, verbose_name='Есть срок действия')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        verbose_name = 'Документ чемпионата'
        verbose_name_plural = 'Документы чемпионата'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        document_kinds.apply_fixed(self)
        super().save(*args, **kwargs)


class ChampionshipOption(models.Model):
    """Шаблонная опция чемпионата — копируется в этапы при registration_mode='all'"""
    championship = models.ForeignKey(
        'organizers.Championship', on_delete=models.CASCADE, related_name='championship_options'
    )
    name = models.CharField(max_length=255, verbose_name='Название')
    description = models.TextField(blank=True, verbose_name='Описание')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Цена (₽)')
    is_mandatory = models.BooleanField(default=False, verbose_name='Обязательная')
    is_active = models.BooleanField(default=True, verbose_name='Доступна')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        verbose_name = 'Опция чемпионата'
        verbose_name_plural = 'Опции чемпионата'

    def __str__(self):
        return f"{self.name} — {self.price} ₽"


class StageOption(models.Model):
    """Дополнительная опция для этапа (слики, дождевая резина, транспондер и т.д.)"""

    stage = models.ForeignKey(
        'organizers.Stage', on_delete=models.CASCADE, related_name='options'
    )
    name = models.CharField(max_length=255, verbose_name='Название')
    description = models.TextField(blank=True, verbose_name='Описание')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Цена (₽)')
    is_mandatory = models.BooleanField(default=False, verbose_name='Обязательная')
    is_active = models.BooleanField(default=True, verbose_name='Доступна')
    source = models.ForeignKey(
        'ChampionshipOption', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stage_copies', verbose_name='Опция чемпионата',
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        verbose_name = 'Доп. опция этапа'
        verbose_name_plural = 'Доп. опции этапа'

    def __str__(self):
        return f"{self.name} — {self.price} ₽"


class ApplicationOption(models.Model):
    """Выбранная доп. опция в заявке — цена фиксируется в момент выбора"""

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='selected_options'
    )
    option = models.ForeignKey(StageOption, on_delete=models.CASCADE)
    price_at_time = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'Выбранная опция'

    def __str__(self):
        return f"{self.option.name} — {self.price_at_time} ₽"


class ApplicationPayment(models.Model):
    """Оплата заявки — сейчас ручная загрузка квитанции, архитектура готова под эквайринг"""

    METHOD_CHOICES = [
        ('manual', 'Ручная оплата (квитанция)'),
        ('online', 'Онлайн оплата'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Ожидает квитанции'),
        ('uploaded', 'На проверке у организатора'),
        ('verified', 'Оплата подтверждена'),
        ('rejected', 'Квитанция отклонена'),
        ('refunded', 'Возвращена'),
    ]

    application = models.OneToOneField(
        Application, on_delete=models.CASCADE, related_name='payment'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Сумма')
    method = models.CharField(
        max_length=20, choices=METHOD_CHOICES, default='manual', verbose_name='Способ оплаты'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='Статус'
    )
    receipt_file = models.FileField(
        upload_to='payment_receipts/%Y/%m/', blank=True, null=True,
        verbose_name='Квитанция об оплате'
    )
    organizer_comment = models.TextField(blank=True, verbose_name='Комментарий организатора')
    # Зарезервировано для будущего эквайринга
    transaction_id = models.CharField(max_length=255, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)

    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_payments'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Оплата заявки'

    def __str__(self):
        return f"{self.amount} ₽ — {self.get_status_display()}"


# ---------------------------------------------------------------------------
# Напоминания об истечении документов из ЛК пилота
# ---------------------------------------------------------------------------

class DocumentReminderSettings(models.Model):
    """Singleton: когда и как напоминать пилоту, что документ в ЛК скоро истечёт.
    Рассылает команда send_document_reminders (cron раз в сутки)."""

    enabled = models.BooleanField('Напоминания включены', default=True)
    days_before = models.CharField(
        'За сколько дней напоминать', max_length=100, default='30, 10, 1',
        help_text='Через запятую, например «30, 10, 1». Одно напоминание на каждый срок.',
    )
    send_email = models.BooleanField('Письмом', default=True)
    send_telegram = models.BooleanField(
        'В Telegram', default=True,
        help_text='Тем, кто подключил уведомления в ЛК (через бота обратной связи).',
    )

    class Meta:
        verbose_name = 'Напоминания о документах'
        verbose_name_plural = 'Напоминания о документах'

    def __str__(self):
        return 'Напоминания о документах'

    @classmethod
    def get(cls):
        obj = cls.objects.first()
        return obj or cls.objects.create()

    def days(self):
        """Сроки по убыванию, без мусора: '30, 10,1, x' -> [30, 10, 1]."""
        values = {int(p) for p in self.days_before.replace(';', ',').split(',') if p.strip().isdigit()}
        return sorted(values, reverse=True)


class DocumentReminder(models.Model):
    """Отметка об отправленном напоминании: не повторять. Срок документа входит в ключ —
    новый файл или новая дата начинают отсчёт заново."""

    document = models.ForeignKey('accounts.PilotDocument', on_delete=models.CASCADE,
                                 related_name='reminders')
    days_before = models.PositiveIntegerField()
    expiry_date = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)
    channels = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name = 'Отправленное напоминание'
        verbose_name_plural = 'Отправленные напоминания'
        constraints = [models.UniqueConstraint(fields=['document', 'days_before', 'expiry_date'],
                                               name='uniq_document_reminder')]
