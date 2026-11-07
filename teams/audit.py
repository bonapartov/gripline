"""Conservative, read-only legacy classification. Evidence is never applied."""
from collections import Counter


def audit_memberships():
    from accounts.models import DriverClaim, UserProfile
    from applications.models import Application
    from teams.models import TeamInvitation
    from website.models import RaceResult, TeamMembership
    counts = Counter(active=0, inactive=0, ambiguous=0)
    counts['accepted_invitations'] = TeamInvitation.objects.filter(status='accepted').count()
    counts['dependent_applications'] = Application.objects.filter(team_entry__isnull=False).count()
    rows = []
    for m in TeamMembership.objects.order_by('pk').iterator():
        counts['active' if m.is_active else 'inactive'] += 1
        invitations = TeamInvitation.objects.filter(team_id=m.team_id, driver_id=m.driver_id)
        accepted = list(invitations.filter(status='accepted'))
        claims = DriverClaim.objects.filter(driver_id=m.driver_id, status='approved')
        has_account = claims.exists() or UserProfile.objects.filter(driver_id=m.driver_id, verified=True).exists()
        apps = Application.objects.filter(team_entry__team_id=m.team_id, pilot__driver_id=m.driver_id)
        dependent = apps.count()
        reasons = []
        if not has_account:
            reasons.append('no_approved_account')
        if not m.is_active or m.left_at:
            reasons.append('ended_membership')
        if TeamMembership.objects.filter(team_id=m.team_id, driver_id=m.driver_id).exclude(pk=m.pk).exists():
            reasons.append('multiple_membership_periods')
        evidence = accepted[0] if len(accepted) == 1 else None
        if not evidence:
            reasons.append('no_unique_accepted_invitation')
        if evidence and (not evidence.responded_at or evidence.responded_at.date() < m.joined_at
                         or evidence.created_at.date() > m.joined_at):
            reasons.append('inconsistent_chronology')
        # Invitation has no responder identity and is overwritten on re-invitation;
        # dates are day-resolution. Even apparently consistent history is not proof.
        if (m.confirmation_state == 'confirmed' and m.confirmed_at and m.confirmed_by_id
                and m.confirmation_source in ('invitation', 'admin_exception')):
            classification = 'explicit_confirmation'
        else:
            classification = 'ambiguous'
            reasons.append('legacy_history_cannot_prove_current_consent')
            counts['ambiguous'] += 1
        rows.append({'membership_id': m.pk, 'team_id': m.team_id, 'driver_id': m.driver_id,
            'active': m.is_active, 'state': m.confirmation_state, 'classification': classification,
            'accepted_invitation_ids': [i.pk for i in accepted], 'reasons': reasons,
            'has_race_history': RaceResult.objects.filter(team_id=m.team_id, driver_id=m.driver_id).exists(),
            'dependent_applications': dependent})
    from django.db.models import Exists, OuterRef
    history_only = list(RaceResult.objects.filter(team__isnull=False, driver__isnull=False)
        .annotate(has_membership=Exists(TeamMembership.objects.filter(
            team_id=OuterRef('team_id'), driver_id=OuterRef('driver_id'))))
        .filter(has_membership=False).order_by().values('team_id', 'driver_id').distinct())
    counts['race_only_pairs'] = len(history_only)
    return {'dry_run': True, 'counts': dict(counts), 'memberships': rows,
            'history_without_membership': history_only}
