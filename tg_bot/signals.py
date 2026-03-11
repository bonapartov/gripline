from django.db.models.signals import post_save
from django.dispatch import receiver
from teams.models import TeamClaim
from accounts.models import DriverClaim
import asyncio
from .notifications import notify_admins_about_team_claim

@receiver(post_save, sender=TeamClaim)
def notify_team_claim(sender, instance, created, **kwargs):
    """Уведомление о новой заявке команды"""
    if created and instance.status == 'pending':
        # Запускаем асинхронную функцию
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        loop.create_task(notify_admins_about_team_claim(instance))
