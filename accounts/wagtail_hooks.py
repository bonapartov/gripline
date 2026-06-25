from wagtail_modeladmin.options import ModelAdmin, modeladmin_register
from django.utils.html import format_html
from .models import DriverClaim


class DriverClaimAdmin(ModelAdmin):
    model = DriverClaim
    menu_label = 'Заявки пилотов'
    menu_icon = 'user'
    list_display = ('user_email', 'full_name', 'driver_link', 'status_badge', 'profile_state', 'created_at')
    list_filter = ('status',)
    search_fields = ('user__email', 'requested_first_name', 'requested_last_name')
    ordering = ('-created_at',)
    inspect_view_enabled = True

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

    def full_name(self, obj):
        return f"{obj.requested_last_name} {obj.requested_first_name}"
    full_name.short_description = 'Имя'

    def driver_link(self, obj):
        if obj.driver:
            return format_html('<span style="color:var(--w-color-positive-100,#28a745)">✓ {}</span>', obj.driver)
        return format_html('<span style="color:#6c757d">— новый пилот</span>')
    driver_link.short_description = 'Пилот в базе'

    def status_badge(self, obj):
        colors = {
            'pending':  ('#ffc107', '#000'),
            'approved': ('#28a745', '#fff'),
            'rejected': ('#dc3545', '#fff'),
        }
        bg, fg = colors.get(obj.status, ('#6c757d', '#fff'))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:4px;font-size:0.85em">{}</span>',
            bg, fg, obj.get_status_display(),
        )
    status_badge.short_description = 'Статус'

    def profile_state(self, obj):
        try:
            profile = obj.user.profile
        except Exception:
            return format_html('<span style="color:#6c757d">нет профиля</span>')
        if 'pilot' in (profile.roles or []):
            return format_html(
                '<span style="color:#28a745">✓ верифицирован</span>'
                '<br><small style="color:#6c757d">{}</small>',
                profile.driver or '—',
            )
        return format_html('<span style="color:#6c757d">не верифицирован</span>')
    profile_state.short_description = 'Профиль'


modeladmin_register(DriverClaimAdmin)
