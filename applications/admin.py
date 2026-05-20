from django.contrib import admin
from .models import (
    Application, ApplicationApplicant, ApplicationPilot, ApplicationKart,
    ApplicationMechanic, ApplicationAchievement,
    StageDocument, ApplicationDocument,
    StageOption, ApplicationOption, ApplicationPayment,
)


class ApplicationPilotInline(admin.StackedInline):
    model = ApplicationPilot
    extra = 0


class ApplicationApplicantInline(admin.StackedInline):
    model = ApplicationApplicant
    extra = 0


class ApplicationKartInline(admin.StackedInline):
    model = ApplicationKart
    extra = 0


class ApplicationMechanicInline(admin.StackedInline):
    model = ApplicationMechanic
    extra = 0


class ApplicationDocumentInline(admin.TabularInline):
    model = ApplicationDocument
    extra = 0


class ApplicationOptionInline(admin.TabularInline):
    model = ApplicationOption
    extra = 0


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ['id', 'get_pilot', 'stage', 'race_class', 'start_number', 'status', 'submitted_by_type', 'created_at']
    list_filter = ['status', 'submitted_by_type', 'stage__championship']
    search_fields = ['pilot__last_name', 'pilot__first_name', 'submitted_by__email']
    inlines = [ApplicationApplicantInline, ApplicationPilotInline, ApplicationKartInline,
               ApplicationMechanicInline, ApplicationDocumentInline, ApplicationOptionInline]

    def get_pilot(self, obj):
        try:
            return obj.pilot.full_name
        except Exception:
            return obj.submitted_by.email
    get_pilot.short_description = 'Пилот'


@admin.register(StageDocument)
class StageDocumentAdmin(admin.ModelAdmin):
    list_display = ['name', 'stage', 'required', 'minors_only', 'has_expiry_date', 'order']
    list_filter = ['stage__championship', 'required', 'minors_only']


@admin.register(StageOption)
class StageOptionAdmin(admin.ModelAdmin):
    list_display = ['name', 'stage', 'price', 'is_mandatory', 'is_active', 'order']
    list_filter = ['stage__championship', 'is_mandatory', 'is_active']
