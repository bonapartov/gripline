from django.dispatch import receiver
from django.db import models
from django.contrib.auth.models import User
from website.models import Track, RaceClass, CompetitionType
from django.db.models.signals import post_save, post_delete, pre_delete
from wagtail.models import Page
from django.utils.text import slugify

class OrganizerProfile(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает активации'),
        ('active', 'Активен'),
        ('rejected', 'Отклонён'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='organizer_profile')
    photo = models.ForeignKey('wagtailimages.Image', on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    telegram = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Оставьте пустым для использования глобальной комиссии")
    commission_payer = models.CharField(max_length=20, choices=[("organizer", "Организатор"), ("participant", "Участник")], null=True, blank=True)

    def __str__(self):
        return f"Organizer: {self.user.email}"
        

class Championship(models.Model):
    organizer = models.ForeignKey(OrganizerProfile, on_delete=models.CASCADE, related_name='championships')
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=False)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    track = models.ForeignKey(Track, on_delete=models.SET_NULL, null=True, blank=True)
    cover_image = models.ForeignKey('wagtailimages.Image', on_delete=models.SET_NULL, null=True, blank=True)
    regulations = models.FileField(upload_to='regulations/', blank=True, null=True)
    budget = models.TextField(blank=True)
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Оставьте пустым для использования настроек организатора")
    commission_payer = models.CharField(max_length=20, choices=[("organizer", "Организатор"), ("participant", "Участник")], null=True, blank=True)
    currency = models.CharField(max_length=3, default='RUB')
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True, verbose_name='Опубликован на сайте')
    is_demo = models.BooleanField(default=False, verbose_name='Демо-мероприятие', help_text='Не публикуется на сайте и не попадает в рейтинг')
    color = models.CharField(max_length=7, default='#ffc107', verbose_name='Цвет в календаре')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    wagtail_page = models.OneToOneField('wagtailcore.Page', on_delete=models.SET_NULL, null=True, blank=True, related_name='championship')
    
    competition_types = models.ManyToManyField(
        CompetitionType,
        blank=True,
        help_text="Типы соревнований (Кубок, Первенство, Чемпионат и т.д.)"
    )
    
    race_classes = models.ManyToManyField(
        'website.RaceClass',
        blank=True,
        help_text="Классы, которые участвуют в чемпионате"
    )

    default_tyres = models.ManyToManyField(
        'website.Tyre',
        blank=True,
        help_text="Разрешённые шины для чемпионата"
    )

    REG_MODE_ALL = 'all'
    REG_MODE_PER_STAGE = 'per_stage'
    REG_MODE_CHOICES = [
        (REG_MODE_PER_STAGE, 'Настройки для каждого этапа отдельно'),
        (REG_MODE_ALL, 'Общие настройки для всех этапов'),
    ]
    registration_mode = models.CharField(
        max_length=20,
        choices=REG_MODE_CHOICES,
        default=REG_MODE_PER_STAGE,
        verbose_name='Режим настроек регистрации',
    )

    TYRE_MODE_ALL = 'all'
    TYRE_MODE_PER_STAGE = 'per_stage'
    TYRE_MODE_CHOICES = [
        (TYRE_MODE_ALL, 'Одни шины для всех этапов'),
        (TYRE_MODE_PER_STAGE, 'Шины на каждый этап отдельно'),
    ]
    tyre_mode = models.CharField(
        max_length=20,
        choices=TYRE_MODE_CHOICES,
        default=TYRE_MODE_ALL,
        verbose_name='Режим назначения шин',
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class Stage(models.Model):
    championship = models.ForeignKey(Championship, on_delete=models.CASCADE, related_name='stages')
    title = models.CharField(max_length=255)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    track = models.ForeignKey(Track, on_delete=models.SET_NULL, null=True, blank=True)
    entry_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    schedule = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    wagtail_page = models.OneToOneField('wagtailcore.Page', on_delete=models.SET_NULL, null=True, blank=True, related_name='stage')

    # Настройки регистрации
    registration_enabled = models.BooleanField(default=True, verbose_name='Регистрация открыта')
    registration_deadline = models.DateTimeField(null=True, blank=True, verbose_name='Дедлайн регистрации')
    late_registration_allowed = models.BooleanField(default=False, verbose_name='Допустить позднюю регистрацию')
    late_registration_fee_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=2.0,
        verbose_name='Множитель позднего взноса'
    )
    max_participants = models.PositiveIntegerField(null=True, blank=True, verbose_name='Макс. участников')

    stage_tyres = models.ManyToManyField(
        'website.Tyre',
        blank=True,
        help_text="Шины для этого этапа (если в чемпионате режим 'per_stage')",
        related_name='stages',
    )

    # Стартовые номера
    start_number_digits = models.PositiveIntegerField(
        default=2,
        choices=[(2, '2-значные (10–99)'), (3, '3-значные (100–999)')],
        verbose_name='Формат стартовых номеров'
    )
    # УТС (учебно-тренировочная сессия) перед этапом — опция организатора. Если включена,
    # пилот выбирает участие: только этап, УТС + этап или только УТС. Формат номеров для
    # «только УТС» организатор выбирает сам: совпадает с форматом этапа — номерная база
    # общая, отличается — у «только УТС» свой диапазон.
    has_training = models.BooleanField(default=False, verbose_name='Перед этапом проводится УТС')
    training_start = models.DateTimeField(null=True, blank=True, verbose_name='Дата и время УТС')
    training_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Взнос за УТС')
    training_number_digits = models.PositiveIntegerField(
        default=2,
        choices=[(2, '2-значные (10–99)'), (3, '3-значные (100–999)')],
        verbose_name='Номера для участников «только УТС»',
    )
    reserved_start_numbers = models.JSONField(
        default=list, blank=True,
        verbose_name='Зарезервированные номера',
        help_text='Номера недоступные для выбора участниками (JSON-список)'
    )

    def __str__(self):
        return f"{self.championship.title} - {self.title}"

    def active_applications(self):
        """Заявки, которые занимают место: всё, кроме отменённых и отклонённых."""
        from applications.models import Application
        return Application.objects.filter(stage=self).exclude(status__in=['rejected', 'cancelled'])

    def race_applications(self):
        """Активные заявки тех, кто едет этап (без «только УТС») — для лимита участников."""
        from applications.models import Application
        return self.active_applications().exclude(participation=Application.PARTICIPATION_TRAINING)

    def participation_choices(self):
        """Варианты участия для формы заявки; без УТС — только этап."""
        from applications.models import Application
        if not self.has_training:
            return [c for c in Application.PARTICIPATION_CHOICES if c[0] == Application.PARTICIPATION_RACE]
        return list(Application.PARTICIPATION_CHOICES)

    @staticmethod
    def _digits_range(digits):
        return range(10, 100) if digits == 2 else range(100, 1000)

    def number_range(self, participation=None):
        """Диапазон стартовых номеров: «только УТС» — по формату номеров УТС, все, кто едет
        этап (в т.ч. «УТС + этап»), — по формату этапа. При одинаковом формате база общая:
        номер в классе занимает любая активная заявка."""
        from applications.models import Application
        if self.has_training and participation == Application.PARTICIPATION_TRAINING:
            return self._digits_range(self.training_number_digits)
        return self._digits_range(self.start_number_digits)

    def separate_training_numbers(self):
        """У «только УТС» свой диапазон номеров (формат отличается от этапа)."""
        return self.has_training and self.training_number_digits != self.start_number_digits

    def entry_fee_now(self):
        """Взнос за этап с учётом позднего множителя после дедлайна."""
        from django.utils import timezone
        fee = self.entry_fee
        if (self.late_registration_allowed and self.registration_deadline
                and timezone.now() > self.registration_deadline):
            fee = fee * self.late_registration_fee_multiplier
        return fee

    def fee_for(self, participation=None):
        """Взнос по варианту участия: этап, УТС + этап (оба взноса) или только УТС."""
        from applications.models import Application
        if not self.has_training or participation in (None, '', Application.PARTICIPATION_RACE):
            return self.entry_fee_now()
        if participation == Application.PARTICIPATION_TRAINING:
            return self.training_fee
        return self.entry_fee_now() + self.training_fee

    def registration_closed_reason(self):
        """None, если заявку подать можно, иначе — причина для участника."""
        from django.utils import timezone
        if not self.registration_enabled:
            return 'Регистрация на этот этап закрыта.'
        if (self.registration_deadline and timezone.now() > self.registration_deadline
                and not self.late_registration_allowed):
            deadline = timezone.localtime(self.registration_deadline).strftime('%d.%m.%Y %H:%M')
            return f'Срок регистрации истёк {deadline}.'
        if self.max_participants and self.race_applications().count() >= self.max_participants:
            return f'Мест нет: набрано {self.max_participants} участников.'
        return None

    def get_available_numbers(self, race_class=None, participation=None):
        """Возвращает список номеров доступных для выбора.
        Если передан race_class — исключает только номера занятые в этом классе;
        диапазон зависит от варианта участия (number_range)."""
        from applications.models import Application
        all_numbers = set(self.number_range(participation))
        reserved = set(self.reserved_start_numbers or [])
        qs = Application.objects.filter(
            stage=self,
            start_number__isnull=False,
        ).exclude(status__in=['rejected', 'cancelled'])
        if race_class is not None:
            qs = qs.filter(race_class=race_class)
        taken = set(qs.values_list('start_number', flat=True))
        return sorted(all_numbers - reserved - taken)


class StaffInvite(models.Model):
    email = models.EmailField()
    organizer = models.ForeignKey(OrganizerProfile, on_delete=models.CASCADE, related_name='staff_invites')
    permissions = models.JSONField(default=dict)
    token = models.CharField(max_length=64, unique=True)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"Invite {self.email} for {self.organizer.user.email}"


class OrganizerSettings(models.Model):
    commission_default = models.DecimalField(max_digits=5, decimal_places=2, default=10.0)
    min_commission = models.DecimalField(max_digits=5, decimal_places=2, default=5.0)
    max_commission = models.DecimalField(max_digits=5, decimal_places=2, default=20.0)
    support_phone = models.CharField(max_length=30, blank=True, default="")
    support_email = models.EmailField(default="support@gripline.ru")
    terms_text = models.TextField(blank=True, default="")
    refund_policy = models.TextField(blank=True, default="")
    payments_enabled = models.BooleanField(
        default=False,
        verbose_name="Оплата включена",
        help_text="Показывать блоки оплаты, комиссий и финансов в ЛК организатора"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Условия для организаторов"
        verbose_name_plural = "Условия для организаторов"

    def __str__(self):
        return f"Глобальные настройки от {self.created_at.strftime('%d.%m.%Y')}"


# ======================
# СИГНАЛЫ ДЛЯ СИНХРОНИЗАЦИИ
# ======================

@receiver(post_save, sender=Stage)
def sync_wagtail_stage(sender, instance, created, **kwargs):
    """Создаёт или обновляет StagePage и EventPage для этапа"""
    from website.models import StagePage, EventPage, EventOccurrence, RaceClassResultGroup
    
    if instance.championship.is_demo:
        return

    parent_page = instance.championship.wagtail_page
    if not parent_page:
        return
    
    if created:
        # СОЗДАНИЕ
        wagtail_stage = StagePage(
            title=instance.title,
            start_date=instance.start_date,
            end_date=instance.end_date,
            track=instance.track,
            live=False,
        )
        parent_page.add_child(instance=wagtail_stage)
        revision = wagtail_stage.save_revision()
        if instance.is_published:
            revision.publish()

        instance.wagtail_page = wagtail_stage
        instance.save()

        for race_class in instance.championship.race_classes.all():
            base_slug = slugify(f"{instance.title}-{race_class.name}")
            slug = base_slug
            counter = 1
            while EventPage.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            event_page = EventPage(
                title=instance.title,
                admin_title=f"{instance.title} - {race_class.name}",
                slug=slug,
                track=instance.track,
                live=False,
            )
            wagtail_stage.add_child(instance=event_page)
            revision = event_page.save_revision()
            if instance.is_published:
                revision.publish()
            
            EventOccurrence.objects.create(
                event=event_page,
                start=instance.start_date,
                end=instance.end_date,
            )
            
            group = RaceClassResultGroup.objects.create(
                page=event_page,
                race_class=race_class,
            )
            
            # default_tyres is now M2M — auto-assignment of a single tyre removed

            # Копируем документы и опции с чемпионата если registration_mode='all'
            if instance.championship.registration_mode == Championship.REG_MODE_ALL:
                from applications.models import ChampionshipDocument, ChampionshipOption, StageDocument, StageOption
                for doc in instance.championship.championship_documents.all():
                    StageDocument.objects.create(
                        stage=instance, source=doc, name=doc.name, description=doc.description,
                        required=doc.required, minors_only=doc.minors_only,
                        has_expiry_date=doc.has_expiry_date, order=doc.order,
                    )
                for opt in instance.championship.championship_options.all():
                    StageOption.objects.create(
                        stage=instance, source=opt, name=opt.name, description=opt.description,
                        price=opt.price, is_mandatory=opt.is_mandatory,
                        is_active=opt.is_active, order=opt.order,
                    )
    else:
        # РЕДАКТИРОВАНИЕ
        if instance.wagtail_page:
            stage_page = instance.wagtail_page.specific
            stage_page.title = instance.title
            stage_page.start_date = instance.start_date
            stage_page.end_date = instance.end_date
            stage_page.track = instance.track
            revision = stage_page.save_revision()
            if instance.is_published:
                revision.publish()
            elif stage_page.live:
                stage_page.unpublish()

            for event_page in EventPage.objects.child_of(stage_page):
                event_page.title = instance.title
                if event_page.admin_title:
                    parts = event_page.admin_title.split(' - ')
                    if len(parts) > 1:
                        event_page.admin_title = f"{instance.title} - {parts[1]}"
                event_page.track = instance.track
                revision = event_page.save_revision()
                if instance.is_published:
                    revision.publish()
                elif event_page.live:
                    event_page.unpublish()

                if event_page.occurrences.exists():
                    occurrence = event_page.occurrences.first()
                    occurrence.start = instance.start_date
                    occurrence.end = instance.end_date
                    occurrence.save()


@receiver(post_delete, sender=Stage)
def delete_wagtail_stage_page(sender, instance, **kwargs):
    """При удалении этапа из БД организаторов удаляем и Wagtail страницу"""
    if instance.wagtail_page:
        instance.wagtail_page.delete()


@receiver(pre_delete, sender=Page)
def delete_organizer_stage_on_wagtail_delete(sender, instance, **kwargs):
    """При удалении StagePage из Wagtail удаляем соответствующий этап из БД организаторов"""
    from .models import Stage
    
    if instance.content_type.model == 'stagepage':
        stage = Stage.objects.filter(wagtail_page=instance).first()
        if stage:
            # Временно отключаем post_delete сигнал, чтобы избежать рекурсии
            post_delete.disconnect(delete_wagtail_stage_page, sender=Stage)
            stage.delete()
            post_delete.connect(delete_wagtail_stage_page, sender=Stage)