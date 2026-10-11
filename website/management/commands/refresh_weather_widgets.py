"""Погодные виджеты этапов и групп результатов — заранее, в БД (WeatherWidgetSnapshot).

Страницы (главная, этап) только читают снимки; Open-Meteo опрашивается здесь, по cron:
    0 */3 * * * cd /www/wwwroot/gripline.ru && venv/bin/python manage.py refresh_weather_widgets

Прогноз обновляется на каждом запуске, оценка по прошлым годам — раз в сутки, архив — один раз
(данные прошедшего дня не меняются). Неудачный запрос не стирает прежний снимок.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from website.dashboard.jobs import record_job


class Command(BaseCommand):
    help = 'Обновить погодные виджеты этапов и групп результатов (Open-Meteo → БД).'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Запросить всё заново, не глядя на свежесть.')

    def handle(self, *args, force=False, **options):
        with record_job('refresh_weather_widgets') as info:
            info['message'] = self._run(force)
            self.stdout.write(info['message'])

    def _targets(self):
        from website.models import RaceClassResultGroup, StagePage
        from website.weather_utils import group_weather_target, stage_weather_target
        for stage in StagePage.objects.live().select_related('track'):
            t = stage_weather_target(stage)
            if t:
                yield 'stage', stage.pk, t
        groups = (RaceClassResultGroup.objects.filter(air_temperature__isnull=True)
                  .select_related('page__track'))
        for group in groups:
            t = group_weather_target(group)
            if t:
                yield 'group', group.pk, t

    def _run(self, force):
        from website.models import WeatherWidgetSnapshot
        from website.weather_utils import fetch_weather_widget, weather_category

        today = timezone.localdate()
        existing = {(s.namespace, s.object_id, s.target_date): s for s in WeatherWidgetSnapshot.objects.all()}
        keep, updated, failed, fresh = set(), 0, 0, 0
        for namespace, object_id, (lat, lon, day) in self._targets():
            key = (namespace, object_id, day)
            keep.add(key)
            snap = existing.get(key)
            category = weather_category(day, today)
            if not force and snap and snap.category == category and (
                    category == 'archive'
                    or (category == 'estimate' and timezone.localtime(snap.fetched_at).date() == today)):
                fresh += 1
                continue
            category, data = fetch_weather_widget(lat, lon, day)
            if not data:
                failed += 1
                continue
            WeatherWidgetSnapshot.objects.update_or_create(
                namespace=namespace, object_id=object_id, target_date=day,
                defaults={'category': category, 'data': data})
            updated += 1
        # Снимки для старых дат (этап перенесли, группу удалили) — не нужны.
        stale = [s.pk for k, s in existing.items() if k not in keep]
        WeatherWidgetSnapshot.objects.filter(pk__in=stale).delete()
        msg = f'обновлено {updated}, свежих {fresh}, не получено {failed}, удалено {len(stale)}'
        if failed and not updated and not fresh:
            raise RuntimeError(f'Open-Meteo: ни одного виджета ({msg})')
        return msg
