# -*- coding: utf-8 -*-
"""
Management-команда для обновления рейтингов шасси и пилотов.
Запуск: python manage.py update_ratings
"""

from django.core.management.base import BaseCommand
from django.db import transaction
import logging
import sys
from pathlib import Path

# Добавляем путь к analytics в sys.path
sys.path.append(str(Path(__file__).parent.parent.parent))

from analytics.core.data_loader import DataLoader
from analytics.core.preprocessing import DataPreprocessor
from analytics.bradley_terriy.model import BradleyTerryLasso


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Обновляет рейтинги шасси и пилотов на основе исторических данных'

    def add_arguments(self, parser):
        parser.add_argument(
            '--entity',
            type=str,
            choices=['chassis', 'driver', 'all'],
            default='all',
            help='Какую сущность ранжировать'
        )
        parser.add_argument(
            '--alpha',
            type=float,
            default=0.1,
            help='Коэффициент L1-регуляризации'
        )

    def handle(self, *args, **options):
        entity = options['entity']
        alpha = options['alpha']

        self.stdout.write(f"Запуск обновления рейтингов для {entity} с alpha={alpha}")

        try:
            # Загружаем данные
            loader = DataLoader()
            df_races = loader.load_all_data()

            # Создаем парные сравнения
            if entity in ['chassis', 'all']:
                self._update_chassis_ratings(df_races, alpha)

            if entity in ['driver', 'all']:
                self._update_driver_ratings(df_races, alpha)

            self.stdout.write(self.style.SUCCESS("Рейтинги успешно обновлены"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Ошибка: {str(e)}"))
            logger.exception("Ошибка при обновлении рейтингов")

    def _update_chassis_ratings(self, df_races, alpha):
        """Обновляет рейтинги шасси."""
        from website.models import Chassis

        self.stdout.write("Обновление рейтингов шасси...")

        # Создаем парные сравнения для шасси
        loader = DataLoader()
        df_comparisons = loader.create_pairwise_comparisons('chassis')

        if len(df_comparisons) == 0:
            self.stdout.write(self.style.WARNING("Нет данных для расчета рейтингов шасси"))
            return

        # Обучаем модель
        model = BradleyTerryLasso(alpha=alpha)
        model.fit(df_comparisons)

        # Получаем все рейтинги
        ratings = model.get_all_ratings()

        # Сохраняем в базу
        with transaction.atomic():
            for chassis_id, rating in ratings.items():
                Chassis.objects.filter(id=chassis_id).update(
                    rating_score=rating,
                    rating_updated_at=timezone.now()
                )

        self.stdout.write(f"Обновлены рейтинги для {len(ratings)} шасси")

    def _update_driver_ratings(self, df_races, alpha):
        """Обновляет рейтинги пилотов."""
        from website.models import Driver

        self.stdout.write("Обновление рейтингов пилотов...")

        # Аналогично шасси
        loader = DataLoader()
        df_comparisons = loader.create_pairwise_comparisons('driver')

        if len(df_comparisons) == 0:
            self.stdout.write(self.style.WARNING("Нет данных для расчета рейтингов пилотов"))
            return

        model = BradleyTerryLasso(alpha=alpha)
        model.fit(df_comparisons)

        ratings = model.get_all_ratings()

        with transaction.atomic():
            for driver_id, rating in ratings.items():
                Driver.objects.filter(id=driver_id).update(
                    rating_score=rating,
                    rating_updated_at=timezone.now()
                )

        self.stdout.write(f"Обновлены рейтинги для {len(ratings)} пилотов")
