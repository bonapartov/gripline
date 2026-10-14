"""Привязка заявок на этапы к пилоту/команде, когда администратор одобряет DriverClaim/
TeamClaim, созданные мастером подачи заявки (новичок без профиля, команда не из списка).

Подписаны после сигналов accounts/teams (порядок регистрации приложений в INSTALLED_APPS
не важен: читаем claim.driver/claim.team из БД, их к этому моменту уже проставили)."""
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='accounts.DriverClaim')
def link_pilots_on_driver_claim_approved(sender, instance, created, **kwargs):
    if instance.status != 'approved':
        return
    driver_id = sender.objects.filter(pk=instance.pk).values_list('driver_id', flat=True).first()
    if driver_id:
        from .models import ApplicationPilot
        ApplicationPilot.objects.filter(driver_claim=instance, driver__isnull=True).update(driver_id=driver_id)


@receiver(post_save, sender='teams.TeamClaim')
def link_applicants_on_team_claim_approved(sender, instance, created, **kwargs):
    if instance.status != 'approved':
        return
    team_id = sender.objects.filter(pk=instance.pk).values_list('team_id', flat=True).first()
    if team_id:
        from .models import ApplicationApplicant
        ApplicationApplicant.objects.filter(team_claim=instance, team__isnull=True).update(team_id=team_id)
