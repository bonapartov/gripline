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

# Confirmation fields cannot be edited as ordinary model fields.
from django.db import transaction
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel, ObjectList
from wagtail_modeladmin.views import CreateView, EditView
from website.models import TeamMembership
from .admin_forms import MembershipAdminForm


class WagtailMembershipForm(MembershipAdminForm, WagtailAdminModelForm):
    pass


class ConfirmMembershipMixin:
    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)
        if form.cleaned_data.get('confirm_no_account'):
            from .access import confirm_membership
            confirm_membership(self.instance, self.request.user, 'admin_exception',
                               form.cleaned_data['exception_reason'])
        return response


class MembershipCreateView(ConfirmMembershipMixin, CreateView):
    pass


class MembershipEditView(ConfirmMembershipMixin, EditView):
    pass


class TeamMembershipAdmin(ModelAdmin):
    model = TeamMembership
    menu_label = 'Состав и доступ'
    menu_icon = 'group'
    list_display = ('driver', 'team', 'is_active', 'confirmation_state', 'confirmation_source',
                    'confirmed_at', 'confirmed_by')
    list_filter = ('confirmation_state', 'is_active', 'confirmation_source', 'team')
    search_fields = ('driver__last_name', 'team__name')
    create_view_class = MembershipCreateView
    edit_view_class = MembershipEditView
    edit_handler = ObjectList([
        *[FieldPanel(f) for f in ('driver', 'team', 'race_class', 'is_active', 'left_at')],
        *[FieldPanel(f, read_only=True) for f in ('confirmation_state', 'confirmation_source',
            'confirmed_at', 'confirmed_by', 'confirmation_reason')],
        FieldPanel('confirm_no_account'), FieldPanel('exception_reason'),
    ], base_form_class=WagtailMembershipForm)


modeladmin_register(TeamMembershipAdmin)
