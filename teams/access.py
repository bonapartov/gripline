"""Shared server-side scope for operational team access.

Legacy is deliberately separate from confirmation: compatibility is temporary,
explicit and must be removed only after a reviewed production audit.
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


def operational_memberships():
    from website.models import TeamMembership
    evidence = Q(confirmation_state='confirmed', confirmed_at__isnull=False,
                 confirmed_by__isnull=False,
                 confirmation_source__in=['invitation', 'admin_exception'])
    if getattr(settings, 'TEAM_ACCESS_LEGACY_ENABLED', True):
        evidence |= Q(confirmation_state='legacy')
    return TeamMembership.objects.filter(evidence, is_active=True, left_at__isnull=True)


def managed_memberships(user):
    from .models import TeamManager
    if not user.is_authenticated or not user.is_active:
        return operational_memberships().none()
    teams = TeamManager.objects.filter(user=user, is_active=True).values('team_id')
    return operational_memberships().filter(team_id__in=teams)


def managed_driver_ids(user):
    return set(managed_memberships(user).values_list('driver_id', flat=True))


def can_manage_driver(user, team_id, driver_id):
    return managed_memberships(user).filter(team_id=team_id, driver_id=driver_id).exists()


@transaction.atomic
def confirm_membership(membership, actor, source, reason='', invitation=None):
    """Only explicit pilot consent or an accountable no-account exception."""
    from accounts.models import DriverClaim, UserProfile
    from .models import MembershipConfirmation, TeamInvitation
    from website.models import TeamMembership
    if source == 'invitation':
        if invitation is None:
            raise PermissionDenied
        invitation = TeamInvitation.objects.select_for_update().get(pk=invitation.pk)
    membership = TeamMembership.objects.select_for_update().get(pk=membership.pk)
    if not actor or not actor.is_active:
        raise PermissionDenied
    if source == 'invitation':
        if (invitation is None or invitation.status != 'pending'
                or invitation.driver_id != membership.driver_id
                or invitation.team_id != membership.team_id
                or not DriverClaim.objects.filter(user=actor, driver_id=membership.driver_id,
                                                  status='approved').exists()):
            raise PermissionDenied
    elif source == 'admin_exception':
        if not (actor.is_superuser or actor.has_perm('website.change_teammembership')):
            raise PermissionDenied
        if not reason.strip():
            raise ValidationError('Укажите основание подтверждения.')
        if (DriverClaim.objects.filter(driver_id=membership.driver_id, status='approved').exists()
                or UserProfile.objects.filter(driver_id=membership.driver_id, verified=True).exists()):
            raise ValidationError('Пилот с аккаунтом должен принять приглашение.')
    else:
        raise ValidationError('Недопустимый источник подтверждения.')
    membership.confirmation_state = 'confirmed'
    membership.confirmed_at = timezone.now()
    membership.confirmed_by = actor
    membership.confirmation_source = source
    membership.confirmation_reason = reason.strip()
    membership.is_active = True
    membership.left_at = None
    membership._explicit_confirmation = True
    membership.save()
    MembershipConfirmation.objects.create(membership=membership, actor=actor,
        source=source, reason=reason.strip(), invitation_id=invitation.pk if invitation else None,
        driver_id_at_confirmation=membership.driver_id, team_id_at_confirmation=membership.team_id)
    if source == 'invitation':
        invitation.status = 'accepted'
        invitation.responded_at = membership.confirmed_at
        invitation.save(update_fields=['status', 'responded_at'])
    return membership


@transaction.atomic
def end_membership(membership):
    from website.models import TeamMembership
    # Keep evidence in the event log; reactivation alone cannot restore consent.
    TeamMembership.objects.filter(pk=membership.pk).update(is_active=False,
        left_at=timezone.localdate(), confirmation_state='unconfirmed', confirmed_at=None,
        confirmed_by=None, confirmation_source='', confirmation_reason='')
