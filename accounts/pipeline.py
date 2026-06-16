from django.shortcuts import redirect


def set_unusable_password(backend, user, response, *args, **kwargs):
    """Ensure OAuth-only users cannot login with a password."""
    if user and not user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])


def setup_onboarding(strategy, backend, user, response, *args, **kwargs):
    """
    After OAuth login, prepare session data for onboarding.

    If the user pre-selected a pilot or team on the choose-role page,
    those IDs are stored via SOCIAL_AUTH_FIELDS_STORED_IN_SESSION and
    forwarded to the onboarding sessions so the onboarding views can
    pre-populate and skip the search step.
    """
    from accounts.models import DriverClaim, UserProfile

    UserProfile.objects.get_or_create(user=user)

    role = strategy.session_get('role', 'pilot')
    if role not in ('pilot', 'team', 'organizer'):
        role = 'pilot'
    strategy.session_set('yandex_role', role)

    # Pre-selected IDs from choose-role modal
    pilot_id = strategy.session_get('pilot_id')
    team_id = strategy.session_get('team_id')
    if pilot_id:
        strategy.session_set('yandex_preselected_pilot_id', pilot_id)
    if team_id:
        strategy.session_set('yandex_preselected_team_id', team_id)

    # If the user already has any DriverClaim the onboarding is done
    has_claim = DriverClaim.objects.filter(user=user).exists()
    if not has_claim:
        strategy.session_set('yandex_onboarding', True)
        strategy.session_set('yandex_first_name', user.first_name)
        strategy.session_set('yandex_last_name', user.last_name)
