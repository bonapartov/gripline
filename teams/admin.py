from django.contrib import admin
from django.utils import timezone
from .models import TeamManager, TeamClaim, TeamJoinRequest
from website.models import TeamMembership

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


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ('driver', 'team', 'race_class', 'is_active', 'confirmed_at',
                    'confirmation_source', 'confirmed_by')
    list_filter = ('is_active', 'confirmation_source', 'team')
    search_fields = ('driver__first_name', 'driver__last_name', 'team__name')
    actions = ('confirm_memberships', 'revoke_confirmation')

    def save_model(self, request, obj, form, change):
        if obj.confirmed_at and not obj.confirmed_by:
            obj.confirmed_by = request.user
        if obj.confirmed_at and not obj.confirmation_source:
            obj.confirmation_source = 'admin'
        super().save_model(request, obj, form, change)

    @admin.action(description='Подтвердить выбранные связи (администратор)')
    def confirm_memberships(self, request, queryset):
        queryset.update(
            confirmed_at=timezone.now(),
            confirmed_by=request.user,
            confirmation_source='admin',
            confirmation_note='Подтверждено администратором',
        )

    @admin.action(description='Снять подтверждение (доступ закроется)')
    def revoke_confirmation(self, request, queryset):
        queryset.update(confirmed_at=None, confirmed_by=None,
                        confirmation_source='', confirmation_note='')
