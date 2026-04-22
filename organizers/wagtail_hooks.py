from wagtail_modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from .models import OrganizerProfile, Championship, Stage, OrganizerSettings

class OrganizerProfileAdmin(ModelAdmin):
    model = OrganizerProfile
    menu_label = "Список"
    menu_icon = "user"
    list_display = ('user', 'phone', 'telegram', 'created_at')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'phone')
    list_filter = ('created_at',)

class ChampionshipAdmin(ModelAdmin):
    model = Championship
    menu_label = "Чемпионаты"
    menu_icon = "trophy"
    list_display = ('title', 'organizer', 'start_date', 'end_date', 'is_active')
    search_fields = ('title', 'organizer__user__email')
    list_filter = ('is_active', 'is_archived')

class StageAdmin(ModelAdmin):
    model = Stage
    menu_label = "Этапы"
    menu_icon = "date"
    list_display = ('title', 'championship', 'start_date', 'end_date', 'entry_fee')
    search_fields = ('title', 'championship__title')
    list_filter = ('championship',)

class OrganizerSettingsAdmin(ModelAdmin):
    model = OrganizerSettings
    menu_label = "Условия"
    menu_icon = "doc-full"
    list_display = ('commission_default', 'min_commission', 'max_commission', 'support_email')
    form_fields_exclude = ('created_at', 'updated_at')

class OrganizersGroup(ModelAdminGroup):
    menu_label = "Организаторы"
    menu_icon = "group"
    items = (OrganizerProfileAdmin, ChampionshipAdmin, StageAdmin, OrganizerSettingsAdmin)

modeladmin_register(OrganizersGroup)
