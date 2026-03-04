from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import TeamClaim, TeamManager

@receiver(post_save, sender=TeamClaim)
def create_team_manager_on_approval(sender, instance, **kwargs):
    """
    При подтверждении заявки (status='approved') автоматически создаем TeamManager
    """
    if instance.status == 'approved' and instance.team:
        # Проверяем, не создан ли уже менеджер
        manager_exists = TeamManager.objects.filter(
            user=instance.user,
            team=instance.team
        ).exists()

        if not manager_exists:
            TeamManager.objects.create(
                user=instance.user,
                team=instance.team,
                role='captain',  # Капитан по умолчанию
                is_active=True
            )
