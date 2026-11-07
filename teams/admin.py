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

from website.models import TeamMembership
from .models import MembershipConfirmation
from .admin_forms import MembershipAdminForm


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    form = MembershipAdminForm
    list_display = ('driver', 'team', 'is_active', 'confirmation_state', 'confirmation_source',
                    'confirmed_at', 'confirmed_by')
    list_filter = ('confirmation_state', 'is_active', 'confirmation_source', 'team')
    readonly_fields = ('joined_at', 'confirmation_state', 'confirmation_source', 'confirmed_at',
                       'confirmed_by', 'confirmation_reason')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form.cleaned_data.get('confirm_no_account'):
            from .access import confirm_membership
            confirm_membership(obj, request.user, 'admin_exception',
                               form.cleaned_data['exception_reason'])


@admin.register(MembershipConfirmation)
class MembershipConfirmationAdmin(admin.ModelAdmin):
    list_display = ('membership', 'actor', 'source', 'created_at')
    readonly_fields = ('membership', 'actor', 'source', 'reason', 'invitation', 'created_at',
                       'driver_id_at_confirmation', 'team_id_at_confirmation')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
