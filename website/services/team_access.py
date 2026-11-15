"""Единая проверка подтверждённого состава команды.

Операционный доступ к документам пилота, его сессиям и привязке новых сессий
дают только активный менеджер конкретной команды и активное подтверждённое
членство пилота именно в этой команде (ТЗ docs/team-access-spec.md).

Подтверждение ставится результатом пилота за команду (решение владельца
15.11.2026), принятым приглашением, одобренной заявкой или администратором.
Исторический/ручной состав без подтверждения остаётся видимым, но доступа
к личным данным не даёт.
"""
from website.models import TeamMembership


def confirmed_memberships(*, team_ids=None, driver_ids=None):
    qs = TeamMembership.objects.filter(is_active=True, confirmed_at__isnull=False)
    if team_ids is not None:
        qs = qs.filter(team_id__in=team_ids)
    if driver_ids is not None:
        qs = qs.filter(driver_id__in=driver_ids)
    return qs


def managed_team_ids(user):
    """Активные команды, которыми управляет пользователь."""
    from teams.models import TeamManager
    if not getattr(user, 'is_authenticated', False):
        return []
    return list(TeamManager.objects.filter(user=user, is_active=True)
                .values_list('team_id', flat=True))


def is_team_manager(user, team_id):
    """Пользователь — активный менеджер именно этой команды."""
    from teams.models import TeamManager
    if not getattr(user, 'is_authenticated', False):
        return False
    return TeamManager.objects.filter(user=user, team_id=team_id, is_active=True).exists()


def confirmed_driver_ids(team_ids):
    return set(confirmed_memberships(team_ids=team_ids).values_list('driver_id', flat=True))


def confirmed_team_ids_for_driver(driver_id):
    return set(confirmed_memberships(driver_ids=[driver_id]).values_list('team_id', flat=True))


def has_confirmed_membership(driver_id, team_id):
    return confirmed_memberships(team_ids=[team_id], driver_ids=[driver_id]).exists()


def can_access_team_vault(user, team_id, driver_id):
    """Менеджер команды + подтверждённый пилот этой команды."""
    return is_team_manager(user, team_id) and has_confirmed_membership(driver_id, team_id)


def allowed_driver_ids(user):
    """Пилоты, которых пользователь может указать в своих сессиях приложения."""
    ids = set()
    profile = getattr(user, 'profile', None)
    if profile is not None and profile.verified and profile.driver_id:
        ids.add(profile.driver_id)
    ids.update(confirmed_driver_ids(managed_team_ids(user)))
    return ids
