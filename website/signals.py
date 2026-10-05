from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib import messages
from .models import RaceClassResultGroup
from .weather_utils import fetch_weather_data
import logging
from django.utils import timezone


logger = logging.getLogger(__name__)

@receiver(post_save, sender=RaceClassResultGroup)
def update_weather_from_api(sender, instance, created, **kwargs):
    """
    Автоматически заполняет погоду при сохранении группы результатов
    """
    # Если у группы уже есть данные о погоде и мы не хотим их перезаписывать
    # Можно добавить флаг, но пока будем заполнять только если пусто

    # Проверяем, есть ли координаты у трассы
    if not instance.page or not instance.page.track:
        logger.info("Нет привязанной трассы, пропускаем запрос погоды")
        return

    track = instance.page.track
    if not track.latitude or not track.longitude:
        logger.info(f"У трассы {track.name} не указаны координаты")
        return

    # Получаем дату окончания этапа
    occurrences = instance.page.occurrences.all()
    if not occurrences:
        logger.info(f"У этапа {instance.page.title} нет даты окончания")
        return

    target_date = occurrences.first().end
    target_time = instance.race_time

    # Запрашиваем погоду
    weather_data = fetch_weather_data(
        latitude=track.latitude,
        longitude=track.longitude,
        target_date=target_date,
        target_time=target_time
    )

    if weather_data:
        # Обновляем поля
        instance.air_temperature = weather_data.get("air_temperature")
        instance.humidity = weather_data.get("humidity")
        instance.pressure = weather_data.get("pressure")
        instance.wind_speed = weather_data.get("wind_speed")
        instance.uv_index = weather_data.get("uv_index")
        instance.precipitation = weather_data.get("precipitation")

        # Сохраняем без вызова сигнала (чтобы избежать рекурсии)
        from django.db.models.signals import post_save
        post_save.disconnect(update_weather_from_api, sender=RaceClassResultGroup)
        instance.save()
        post_save.connect(update_weather_from_api, sender=RaceClassResultGroup)

        logger.info(f"Погода для группы {instance.id} успешно обновлена")
    else:
        logger.warning(f"Не удалось получить погоду для группы {instance.id}")
from .models import RaceResult, TeamMembership

@receiver(post_save, sender=RaceResult)
def create_team_membership(sender, instance, created, **kwargs):
    """
    Автоматически создаёт членство пилота в команде при добавлении результата
    """
    if instance.team and instance.driver:
        membership, created = TeamMembership.objects.get_or_create(
            driver=instance.driver,
            team=instance.team,
            defaults={
                'is_active': True,
                'joined_at': instance.group.page.last_published_at.date() if instance.group.page.last_published_at else timezone.now().date()
            }
        )
        if created:
            logger.info(f'Автоматически создано членство: {instance.driver.full_name} → {instance.team.name}')

# ── Футер из админки ─────────────────────────────────────────────────────────
# Футер сайта — сниппет CodeRed «Footers» (templates/coderedcms/snippets/footer.html).
# wagtailcache держит готовые страницы целиком, а правка сниппета его не сбрасывает —
# без этого изменения в админке не были бы видны посетителям до истечения срока кэша.
def _clear_page_cache(**kwargs):
    try:
        from wagtailcache.cache import clear_cache
        clear_cache()
    except Exception:  # кэш — удобство, а не причина ронять сохранение в админке
        logger.exception('footer: не удалось сбросить wagtailcache')


def _connect_footer_cache_signals():
    from coderedcms.models import Footer, FooterOrderable
    from django.db.models.signals import post_delete
    for model in (Footer, FooterOrderable):
        post_save.connect(_clear_page_cache, sender=model, dispatch_uid=f'footer_cache_save_{model.__name__}')
        post_delete.connect(_clear_page_cache, sender=model, dispatch_uid=f'footer_cache_del_{model.__name__}')


_connect_footer_cache_signals()
