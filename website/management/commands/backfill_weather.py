# -*- coding: utf-8 -*-
"""
Добивает погоду для групп результатов (RaceClassResultGroup), у которых
она пустая. Запуск: python manage.py backfill_weather

Зачем нужна отдельно от сигнала (website/signals.py::update_weather_from_api):
сигнал бьёт в архивный API Open-Meteo один раз, в момент сохранения группы —
а страницы этапов обычно публикуются заранее (недели-месяцы до гонки), когда
у архива ещё физически нет данных на эту дату. Запрос тихо проваливается,
и поле остаётся NULL навсегда, пока кто-то не пересохранит группу вручную
после гонки. Эта команда — то самое пересохранение, но пакетом и по расписанию
(имеет смысл гонять её периодически, например раз в неделю через cron).
"""

from django.core.management.base import BaseCommand
from website.models import RaceClassResultGroup
from website.weather_utils import fetch_weather_data


class Command(BaseCommand):
    help = 'Добивает погоду для групп результатов, у которых она ещё не заполнена'

    def handle(self, *args, **options):
        groups = RaceClassResultGroup.objects.filter(air_temperature__isnull=True).select_related('page__track')

        updated = 0
        skipped_no_track = 0
        skipped_no_occurrence = 0
        failed = 0

        for group in groups:
            page = group.page
            track = page.track if page else None
            if not track or track.latitude is None or track.longitude is None:
                skipped_no_track += 1
                continue

            occurrence = page.occurrences.first()
            if not occurrence:
                skipped_no_occurrence += 1
                continue

            weather_data = fetch_weather_data(
                latitude=track.latitude,
                longitude=track.longitude,
                target_date=occurrence.end,
                target_time=group.race_time,
            )

            if not weather_data:
                failed += 1
                continue

            RaceClassResultGroup.objects.filter(pk=group.pk).update(**weather_data)
            updated += 1
            self.stdout.write(f'  Группа {group.pk} ({page.title if page else "?"}): погода обновлена')

        self.stdout.write(self.style.SUCCESS(
            f'Готово. Обновлено: {updated}. '
            f'Без трассы/координат: {skipped_no_track}. '
            f'Без даты этапа: {skipped_no_occurrence}. '
            f'Данных в API ещё нет (дата слишком свежая/будущая): {failed}.'
        ))
