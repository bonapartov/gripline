from django.db.models.signals import post_save, post_delete
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import UserProfile


def _sync_roles(user):
    """Пересчитывает roles/driver/team/verified для UserProfile на основе источников правды."""
    from .models import DriverClaim
    from teams.models import TeamManager

    profile, _ = UserProfile.objects.get_or_create(user=user)

    roles = []
    driver = None
    team = None
    verified = False

    approved_claim = (
        DriverClaim.objects
        .filter(user=user, status='approved')
        .select_related('driver')
        .first()
    )
    if approved_claim and approved_claim.driver:
        roles.append('pilot')
        driver = approved_claim.driver
        verified = True

    active_mgr = (
        TeamManager.objects
        .filter(user=user, is_active=True)
        .select_related('team')
        .first()
    )
    if active_mgr:
        roles.append('manager')
        team = active_mgr.team

    UserProfile.objects.filter(pk=profile.pk).update(
        roles=roles,
        driver=driver,
        team=team,
        verified=verified,
    )


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()
    else:
        UserProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender='accounts.DriverClaim')
def on_driver_claim_save(sender, instance, **kwargs):
    _sync_roles(instance.user)


@receiver(post_save, sender='teams.TeamManager')
def on_team_manager_save(sender, instance, **kwargs):
    _sync_roles(instance.user)


@receiver(post_delete, sender='teams.TeamManager')
def on_team_manager_delete(sender, instance, **kwargs):
    _sync_roles(instance.user)
