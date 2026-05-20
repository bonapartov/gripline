from django.dispatch import receiver
from django.db import models
from django.contrib.auth.models import User
from website.models import Track, RaceClass, CompetitionType
from django.db.models.signals import post_save, post_delete, pre_delete
from wagtail.models import Page
from django.utils.text import slugify

class OrganizerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='organizer_profile')
    photo = models.ForeignKey('wagtailimages.Image', on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    telegram = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
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
    
    default_tyre = models.ForeignKey(
        'website.Tyre',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Шина по умолчанию для всех классов"
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

    # Стартовые номера
    start_number_digits = models.PositiveIntegerField(
        default=2,
        choices=[(2, '2-значные (10–99)'), (3, '3-значные (100–999)')],
        verbose_name='Формат стартовых номеров'
    )
    reserved_start_numbers = models.JSONField(
        default=list, blank=True,
        verbose_name='Зарезервированные номера',
        help_text='Номера недоступные для выбора участниками (JSON-список)'
    )

    def __str__(self):
        return f"{self.championship.title} - {self.title}"

    def get_available_numbers(self):
        """Возвращает список номеров доступных для выбора"""
        from applications.models import Application
        if self.start_number_digits == 2:
            all_numbers = set(range(10, 100))
        else:
            all_numbers = set(range(100, 1000))
        reserved = set(self.reserved_start_numbers or [])
        taken = set(
            Application.objects.filter(
                stage=self,
                start_number__isnull=False,
            ).exclude(
                status__in=['rejected', 'cancelled']
            ).values_list('start_number', flat=True)
        )
        return sorted(all_numbers - reserved - taken)


class Registration(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('paid', 'Paid'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name='registrations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='registrations')
    race_class = models.ForeignKey(RaceClass, on_delete=models.CASCADE)
    start_number = models.PositiveIntegerField(null=True, blank=True)
    driver = models.ForeignKey('website.Driver', on_delete=models.SET_NULL, null=True, blank=True)
    team = models.ForeignKey('website.Team', on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    promo_code = models.CharField(max_length=50, blank=True)
    documents = models.FileField(upload_to='registrations/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.stage.title}"


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
        )
        parent_page.add_child(instance=wagtail_stage)
        wagtail_stage.save_revision().publish()
        
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
            )
            wagtail_stage.add_child(instance=event_page)
            event_page.save_revision().publish()
            
            EventOccurrence.objects.create(
                event=event_page,
                start=instance.start_date,
                end=instance.end_date,
            )
            
            group = RaceClassResultGroup.objects.create(
                page=event_page,
                race_class=race_class,
            )
            
            if instance.championship.default_tyre:
                group.tyre = instance.championship.default_tyre
                group.save()
    else:
        # РЕДАКТИРОВАНИЕ
        if instance.wagtail_page:
            stage_page = instance.wagtail_page.specific
            stage_page.title = instance.title
            stage_page.start_date = instance.start_date
            stage_page.end_date = instance.end_date
            stage_page.track = instance.track
            stage_page.save_revision().publish()
            
            for event_page in EventPage.objects.child_of(stage_page).live():
                event_page.title = instance.title
                if event_page.admin_title:
                    parts = event_page.admin_title.split(' - ')
                    if len(parts) > 1:
                        event_page.admin_title = f"{instance.title} - {parts[1]}"
                event_page.track = instance.track
                event_page.save_revision().publish()
                
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