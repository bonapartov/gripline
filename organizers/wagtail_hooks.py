from wagtail_modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from .models import OrganizerProfile, Championship, Stage, OrganizerSettings


class OrganizerProfileAdmin(ModelAdmin):
    model = OrganizerProfile
    menu_label = "Организаторы"
    menu_icon = "user"
    list_display = ('user_email', 'phone', 'telegram', 'status', 'created_at')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'phone')
    list_filter = ('status', 'created_at')
    ordering = ('-created_at',)

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
    list_display = ('name', 'championship', 'required', 'minors_only', 'has_expiry_date')
    search_fields = ('name', 'championship__title')
    list_filter = ('championship', 'required', 'minors_only')


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
    list_display = ('name', 'stage', 'required', 'minors_only')
    search_fields = ('name', 'stage__title', 'stage__championship__title')
    list_filter = ('required', 'minors_only')


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


class OrganizersGroup(ModelAdminGroup):
    menu_label = "Организаторы"
    menu_icon = "group"
    items = (
        OrganizerProfileAdmin,
        ChampionshipAdmin,
        StageAdmin,
        ChampionshipDocumentAdmin,
        ChampionshipOptionAdmin,
        StageDocumentAdmin,
        StageOptionAdmin,
        OrganizerSettingsAdmin,
    )


modeladmin_register(OrganizersGroup)
