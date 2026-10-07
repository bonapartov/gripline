from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import TeamClaim, TeamManager


@receiver(pre_save, sender=TeamClaim)
def stash_old_team_claim_state(sender, instance, **kwargs):
    """Запоминает статус и команду до сохранения — чтобы письма уходили только при смене."""
    old = sender.objects.filter(pk=instance.pk).values('status', 'team_id').first() if instance.pk else None
    instance._old_status = old['status'] if old else None
    instance._old_team_id = old['team_id'] if old else None


@receiver(post_save, sender=TeamClaim)
def create_team_manager_on_approval(sender, instance, created=False, **kwargs):
    """
    Подтверждение заявки (status='approved'):
    - команда не выбрана админом → создаём её по запрошенному названию (заявка на «новую команду»);
    - создаём TeamManager (капитан), если его ещё нет.
    Отказ (status='rejected') — снимаем менеджера этой команды, если он уже был (старые заявки,
    созданные до того, как менеджер стал выдаваться только после подтверждения).
    """
    if instance.status == 'approved':
        # автосоздание команды — только при переходе в «подтверждено» (решение админа),
        # не при создании уже подтверждённой записи скриптом
        if (not instance.team_id and instance.requested_team_name.strip()
                and not created and getattr(instance, '_old_status', None) != 'approved'):
            from website.models import Team
            team = Team.objects.create(name=instance.requested_team_name.strip(),
                                       city=instance.requested_city or None)
            TeamClaim.objects.filter(pk=instance.pk).update(team=team)
            instance.team = team
        if instance.team:
            manager, created = TeamManager.objects.get_or_create(
                user=instance.user, team=instance.team,
                defaults={'role': 'captain', 'is_active': True},
            )
            if not created and not manager.is_active:
                manager.is_active = True
                manager.save()
    elif instance.status == 'rejected' and instance.team_id:
        for manager in TeamManager.objects.filter(user=instance.user, team=instance.team, is_active=True):
            manager.is_active = False
            manager.save()  # post_save пересчитает роли профиля


@receiver(post_save, sender=TeamClaim)
def notify_on_team_claim_save(sender, instance, created, **kwargs):
    """Админу — о новой заявке; менеджеру — о приёме, подтверждении и отказе."""
    from accounts.signals import (send_team_claim_approved_email, send_team_claim_pending_email,
                                  send_team_claim_rejected_email)

    if created:
        if instance.status == 'pending':
            send_team_claim_pending_email(instance.user, instance)
            from website.claim_notify import notify_admins_new_claim
            transaction.on_commit(lambda: notify_admins_new_claim(instance))
        return

    old_status = getattr(instance, '_old_status', None)
    old_team_id = getattr(instance, '_old_team_id', None)
    # «Подтверждена» — только когда команда выбрана: без неё роль менеджера не выдаётся
    # (TeamManager не создаётся), и письмо о подтверждении вводило бы в заблуждение.
    # Если админ выбрал команду позже, чем поставил статус, письмо уходит в этот момент.
    became_approved = (instance.status == 'approved' and instance.team_id
                       and (old_status != 'approved' or old_team_id is None))
    if became_approved:
        send_team_claim_approved_email(instance.user, instance)
    elif instance.status == 'rejected' and old_status != 'rejected':
        send_team_claim_rejected_email(instance.user, instance)
