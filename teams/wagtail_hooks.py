from wagtail_modeladmin.options import ModelAdmin, ModelAdminGroup, modeladmin_register
from django.utils.html import format_html
from .models import TeamClaim, TeamManager, TeamJoinRequest


class TeamClaimAdmin(ModelAdmin):
    model = TeamClaim
    menu_label = 'Заявки команд'
    menu_icon = 'group'
    list_display = ('user_email', 'requested_team_name', 'team_link', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('user__email', 'requested_team_name')
    ordering = ('-created_at',)

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

    def team_link(self, obj):
        if obj.team:
            return format_html('<span style="color:#28a745">✓ {}</span>', obj.team.name)
        return format_html('<span style="color:#6c757d">— новая</span>')
    team_link.short_description = 'Команда в базе'


class TeamManagerAdmin(ModelAdmin):
    model = TeamManager
    menu_label = 'Менеджеры команд'
    menu_icon = 'group'
    list_display = ('user_email', 'team', 'role', 'is_active', 'created_at')
    list_filter = ('is_active', 'role')
    search_fields = ('user__email', 'team__name')

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'


class TeamJoinRequestAdmin(ModelAdmin):
    model = TeamJoinRequest
    menu_label = 'Заявки в команды'
    menu_icon = 'group'
    list_display = ('driver', 'team', 'status', 'created_at')
    list_filter = ('status',)


class TeamsClaimsGroup(ModelAdminGroup):
    menu_label = 'Заявки команд'
    menu_icon = 'group'
    items = (TeamClaimAdmin, TeamManagerAdmin, TeamJoinRequestAdmin)


modeladmin_register(TeamsClaimsGroup)
