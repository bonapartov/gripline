from django.contrib import admin
from .models import TeamManager, TeamClaim, TeamJoinRequest

@admin.register(TeamManager)
class TeamManagerAdmin(admin.ModelAdmin):
    list_display = ('team', 'user_email', 'role', 'is_active')
    list_filter = ('role', 'is_active')

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

@admin.register(TeamClaim)
class TeamClaimAdmin(admin.ModelAdmin):
    list_display = ('requested_team_name', 'user_email', 'status', 'created_at')
    list_filter = ('status',)

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

@admin.register(TeamJoinRequest)
class TeamJoinRequestAdmin(admin.ModelAdmin):
    list_display = ('driver', 'team', 'status', 'created_at')
    list_filter = ('status', 'team')
