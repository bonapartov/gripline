from wagtail_modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from wagtail import hooks
from django.utils.html import format_html
from .models import DriverClaim


class DriverClaimAdmin(ModelAdmin):
    model = DriverClaim
    menu_label = 'Заявки пилотов'
    menu_icon = 'user'
    list_display = ('user_email', 'full_name', 'driver_link', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('user__email', 'requested_first_name', 'requested_last_name')
    ordering = ('-created_at',)

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

    def full_name(self, obj):
        return f"{obj.requested_first_name} {obj.requested_last_name}"
    full_name.short_description = 'Имя'

    def driver_link(self, obj):
        if obj.driver:
            return format_html('<span style="color:#28a745">✓ {}</span>', obj.driver)
        return format_html('<span style="color:#6c757d">— новый</span>')
    driver_link.short_description = 'Пилот в базе'


modeladmin_register(DriverClaimAdmin)
