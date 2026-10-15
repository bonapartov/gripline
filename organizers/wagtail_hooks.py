from django import forms
from django.contrib.auth.models import User
from django.db import transaction
from wagtail.admin.panels import FieldPanel, ObjectList
from wagtail_modeladmin.helpers import PermissionHelper
from wagtail_modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from wagtail_modeladmin.views import EditView
from applications.wagtail_hooks import ApplicationAdmin
from .models import OrganizerProfile, Championship, Stage, OrganizerSettings


class OrganizerUserForm(forms.ModelForm):
    """Имя и email учётной записи организатора (вход — по email)."""
    class Meta:
        model = User
        fields = ['last_name', 'first_name', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True
        self.use_required_attribute = False

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Этот email уже занят другим пользователем.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        # Логин организатора совпадает с email (OrganizerRegistrationForm) — меняем вместе.
        if self.instance.username.lower() == (self.initial.get('email') or '').lower():
            user.username = user.email
        if commit:
            user.save()
        return user


class OrganizerEditView(EditView):
    """Профиль организатора и его учётная запись — одной формой."""

    def user_form(self):
        if not hasattr(self, '_user_form'):
            data = self.request.POST if self.request.method == 'POST' else None
            self._user_form = OrganizerUserForm(data, prefix='user', instance=self.instance.user)
        return self._user_form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_form'] = self.user_form()
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        user_form = self.user_form()
        if not (form.is_valid() & user_form.is_valid()):
            return self.form_invalid(form)
        with transaction.atomic():
            user_form.save()
            return self.form_valid(form)


class NoCreatePermissionHelper(PermissionHelper):
    """Организатор регистрируется сам (/organizers/register/) — «Добавить» в админке не нужен."""
    def user_can_create(self, user):
        return False


class OrganizerProfileAdmin(ModelAdmin):
    model = OrganizerProfile
    menu_label = "Организаторы"
    menu_icon = "user"
    permission_helper_class = NoCreatePermissionHelper
    edit_view_class = OrganizerEditView
    edit_template_name = 'organizers/admin/organizer_edit.html'
    list_display = ('user_name', 'user_email', 'phone', 'telegram', 'status', 'created_at')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'phone')
    list_filter = ('status', 'created_at')
    ordering = ('-created_at',)
    list_select_related = ('user',)
    edit_handler = ObjectList([
        FieldPanel('status'), FieldPanel('phone'), FieldPanel('telegram'), FieldPanel('website'),
        FieldPanel('photo'), FieldPanel('commission_percent'), FieldPanel('commission_payer'),
    ])

    def user_name(self, obj):
        return obj.user.get_full_name() or '—'
    user_name.short_description = 'Имя'

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'


class ChampionshipAdmin(ModelAdmin):
    model = Championship
    menu_label = "Мероприятия"
    menu_icon = "trophy"
    list_display = ('title', 'organizer', 'tyre_mode', 'registration_mode', 'is_published', 'is_active')
    search_fields = ('title', 'organizer__user__email')
    list_filter = ('is_active', 'is_archived', 'is_published', 'tyre_mode', 'registration_mode')
    form_fields_exclude = ('created_at', 'updated_at', 'slug', 'wagtail_page', 'color')


class StageAdmin(ModelAdmin):
    model = Stage
    menu_label = "Этапы"
    menu_icon = "date"
    list_display = ('title', 'championship', 'start_date', 'end_date', 'entry_fee', 'is_published', 'registration_enabled')
    search_fields = ('title', 'championship__title')
    list_filter = ('championship', 'is_published', 'registration_enabled')
    form_fields_exclude = ('wagtail_page', 'reserved_start_numbers')


class ChampionshipDocumentAdmin(ModelAdmin):
    from applications.models import ChampionshipDocument
    model = ChampionshipDocument
    menu_label = "Документы мероприятий"
    menu_icon = "doc-full"
    list_display = ('name', 'kind', 'championship', 'required', 'minors_only', 'has_expiry_date')
    search_fields = ('name', 'championship__title')
    list_filter = ('kind', 'championship', 'required', 'minors_only')


class ChampionshipOptionAdmin(ModelAdmin):
    from applications.models import ChampionshipOption
    model = ChampionshipOption
    menu_label = "Опции мероприятий"
    menu_icon = "list-ul"
    list_display = ('name', 'championship', 'price', 'is_mandatory', 'is_active')
    search_fields = ('name', 'championship__title')
    list_filter = ('championship', 'is_mandatory', 'is_active')


class StageDocumentAdmin(ModelAdmin):
    from applications.models import StageDocument
    model = StageDocument
    menu_label = "Документы этапов"
    menu_icon = "doc-full-inverse"
    list_display = ('name', 'kind', 'stage', 'required', 'minors_only')
    search_fields = ('name', 'stage__title', 'stage__championship__title')
    list_filter = ('kind', 'required', 'minors_only')


class StageOptionAdmin(ModelAdmin):
    from applications.models import StageOption
    model = StageOption
    menu_label = "Опции этапов"
    menu_icon = "list-ul"
    list_display = ('name', 'stage', 'price', 'is_mandatory', 'is_active')
    search_fields = ('name', 'stage__title')
    list_filter = ('is_mandatory', 'is_active')


class OrganizerSettingsAdmin(ModelAdmin):
    model = OrganizerSettings
    menu_label = "Условия платформы"
    menu_icon = "doc-full"
    list_display = ('commission_default', 'min_commission', 'max_commission', 'support_email')
    form_fields_exclude = ('created_at', 'updated_at')


class DocumentReminderSettingsAdmin(ModelAdmin):
    from applications.models import DocumentReminderSettings
    model = DocumentReminderSettings
    menu_label = "Напоминания о документах"
    menu_icon = "date"
    list_display = ('__str__', 'enabled', 'days_before', 'send_email', 'send_telegram')

    def get_queryset(self, request):
        self.model.get()  # единственная запись создаётся при первом открытии
        return super().get_queryset(request)


class OrganizersGroup(ModelAdminGroup):
    menu_label = "Организаторы"
    menu_icon = "group"
    items = (
        ApplicationAdmin,
        OrganizerProfileAdmin,
        ChampionshipAdmin,
        StageAdmin,
        ChampionshipDocumentAdmin,
        ChampionshipOptionAdmin,
        StageDocumentAdmin,
        StageOptionAdmin,
        OrganizerSettingsAdmin,
        DocumentReminderSettingsAdmin,
    )


modeladmin_register(OrganizersGroup)
