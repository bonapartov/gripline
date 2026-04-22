# -*- coding: utf-8 -*-
"""
Management-команда для обновления рейтингов пилотов и шасси.
Запуск: python manage.py update_ratings [--alpha 0.1] [--damping 0.85] [--model bt|pr|ensemble|context|all]
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
import logging
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from analytics.core.data_loader import DataLoader
from analytics.bradley_terry.model import BradleyTerryLasso
from analytics.pagerank.model import ModifiedPageRank
from analytics.ensemble.model import EnsembleRanking
from analytics.ensemble.train import calculate_ensemble_by_class
from analytics.context.weather_model import ContextAwareBradleyTerry
from analytics.context.train import train_context_model_by_class
from website.models import Driver, Chassis, RaceClass

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Обновляет рейтинги пилотов и шасси (Брэдли-Терри, PageRank, Ансамбль, Context-Aware)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--entity',
            type=str,
            choices=['driver', 'chassis', 'all'],
            default='all',
            help='Какую сущность ранжировать'
        )
        parser.add_argument(
            '--model',
            type=str,
            choices=['bt', 'pr', 'ensemble', 'context', 'all'],
            default='all',
            help='Какую модель использовать (bt=Брэдли-Терри, pr=PageRank, ensemble=ансамбль, context=context-aware, all=все)'
        )
        parser.add_argument(
            '--alpha',
            type=float,
            default=0.1,
            help='Коэффициент L1-регуляризации для Брэдли-Терри'
        )
        parser.add_argument(
            '--damping',
            type=float,
            default=0.85,
            help='Демпфирующий фактор для PageRank (по умолчанию 0.85)'
        )
        parser.add_argument(
            '--min-starts',
            type=int,
            default=3,
            help='Минимальное количество стартов для уверенного рейтинга'
        )
        parser.add_argument(
            '--optimize',
            action='store_true',
            default=True,
            help='Оптимизировать веса для ансамбля'
        )

    def handle(self, *args, **options):
        entity = options['entity']
        model = options['model']
        alpha = options['alpha']
        damping = options['damping']
        min_starts = options['min_starts']
        optimize = options['optimize']

        self.stdout.write(f"Запуск обновления рейтингов")
        self.stdout.write(f"  Сущности: {entity}")
        self.stdout.write(f"  Модели: {model}")
        self.stdout.write(f"  alpha (БТ): {alpha}")
        self.stdout.write(f"  damping (PR): {damping}")

        try:
            loader = DataLoader()
            df_races = loader.load_all_data()

            if df_races.empty:
                self.stdout.write(self.style.WARNING("Нет данных для расчета рейтингов"))
                return

            bt_ratings = {}
            pr_ratings = {}

            if entity in ['driver', 'all']:
                bt_res, pr_res = self._update_driver_ratings(
                    loader, model, alpha, damping, min_starts, optimize
                )
                bt_ratings.update(bt_res)
                pr_ratings.update(pr_res)

            if entity in ['chassis', 'all']:
                self._update_chassis_ratings(loader, model, alpha, damping, min_starts)

            # ✅ Сохраняем дату последнего обновления в БД
            from website.models import AnalyticsMetadata
            from django.utils import timezone

            obj, created = AnalyticsMetadata.objects.update_or_create(
                key='last_updated',
                defaults={'value': timezone.now()}
            )
            self.stdout.write(f"  Дата обновления сохранена в БД (ID: {obj.id})")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Ошибка: {str(e)}"))
            logger.exception("Ошибка при обновлении рейтингов")
            import traceback
            traceback.print_exc()

    def _update_driver_ratings(self, loader, model_type, alpha, damping, min_starts, optimize):
        """Обновляет рейтинги пилотов."""
        self.stdout.write("\n=== ПИЛОТЫ ===")

        bt_ratings = {}
        pr_ratings = {}

        if model_type in ['bt', 'all']:
            bt_ratings = self._update_driver_bt_ratings(loader, alpha, min_starts)

        if model_type in ['pr', 'all']:
            pr_ratings = self._update_driver_pr_ratings(loader, damping)

        if model_type in ['ensemble', 'all'] and bt_ratings and pr_ratings:
            self._update_driver_ensemble_ratings(loader, bt_ratings, pr_ratings, optimize)

        if model_type in ['context', 'all']:
            self._update_driver_context_ratings(loader, alpha)

        return bt_ratings, pr_ratings

    def _update_driver_bt_ratings(self, loader, alpha, min_starts):
        """Обновляет рейтинги пилотов по модели Брэдли-Терри."""
        self.stdout.write("  Брэдли-Терри:")

        from website.models import RaceResult

        classes = RaceClass.objects.all()
        bt_ratings = {}

        for race_class in classes:
            self.stdout.write(f"    Класс {race_class.name}...")

            df_class = loader.df_races[loader.df_races['class_id'] == race_class.id].copy()

            if len(df_class) < 5:
                self.stdout.write(f"      Недостаточно данных")
                continue

            df_comparisons = self._create_class_comparisons(df_class, 'driver')

            if len(df_comparisons) < 10:
                self.stdout.write(f"      Недостаточно сравнений")
                continue

            model = BradleyTerryLasso(alpha=alpha)
            model.fit(df_comparisons)

            ratings = model.get_all_ratings()
            bt_ratings[race_class.id] = ratings

            with transaction.atomic():
                for driver_id, score in ratings.items():
                    driver_starts = len(df_class[df_class['driver_id'] == driver_id])
                    driver = Driver.objects.get(id=driver_id)

                    if not driver.rating_by_class:
                        driver.rating_by_class = {}

                    driver.rating_by_class[str(race_class.id)] = {
                        'score': float(score),
                        'starts': driver_starts,
                        'updated': timezone.now().isoformat()
                    }
                    driver.save()

            self.stdout.write(f"      Обновлено {len(ratings)} пилотов")

        return bt_ratings

    def _update_driver_pr_ratings(self, loader, damping):
        """Обновляет рейтинги пилотов по модели PageRank."""
        self.stdout.write("  PageRank:")

        from analytics.pagerank.train import calculate_pagerank_by_class

        pr_results = calculate_pagerank_by_class(
            data_loader=loader,
            entity_type='driver',
            damping=damping
        )

        with transaction.atomic():
            for class_id, ratings in pr_results.items():
                self.stdout.write(f"    Класс ID {class_id}...")

                for driver_id, score in ratings.items():
                    try:
                        driver = Driver.objects.get(id=driver_id)

                        if not driver.pagerank_by_class:
                            driver.pagerank_by_class = {}

                        driver.pagerank_by_class[str(class_id)] = {
                            'score': float(score),
                            'updated': timezone.now().isoformat()
                        }
                        driver.save()
                    except Driver.DoesNotExist:
                        continue

                self.stdout.write(f"      Обновлено {len(ratings)} пилотов")

        return pr_results

    def _update_driver_ensemble_ratings(self, loader, bt_ratings, pr_ratings, optimize):
        """Обновляет рейтинги пилотов по модели ансамбля."""
        self.stdout.write("  Ансамбль:")

        # Рассчитываем ансамбль
        ensemble_results, weights_by_class = calculate_ensemble_by_class(
            data_loader=loader,
            bt_ratings=bt_ratings,
            pr_ratings=pr_ratings,
            optimize=optimize
        )

        with transaction.atomic():
            for class_id, ratings in ensemble_results.items():
                self.stdout.write(f"    Класс ID {class_id}...")

                # Показываем веса для этого класса
                if class_id in weights_by_class:
                    weights = weights_by_class[class_id]
                    self.stdout.write(f"      Веса: BT={weights.get('bradley_terry', 0.5):.2f}, "
                                     f"PR={weights.get('pagerank', 0.5):.2f}")

                for driver_id, score in ratings.items():
                    try:
                        driver = Driver.objects.get(id=driver_id)

                        if not driver.ensemble_by_class:
                            driver.ensemble_by_class = {}

                        # Получаем количество стартов из BT или PR
                        starts = 0
                        if str(class_id) in driver.rating_by_class:
                            starts = driver.rating_by_class[str(class_id)].get('starts', 0)

                        driver.ensemble_by_class[str(class_id)] = {
                            'score': float(score),
                            'starts': starts,
                            'updated': timezone.now().isoformat()
                        }
                        driver.save()
                    except Driver.DoesNotExist:
                        continue

                self.stdout.write(f"      Обновлено {len(ratings)} пилотов")

    def _update_driver_context_ratings(self, loader, alpha):
        """Обновляет рейтинги пилотов по контекстной модели."""
        self.stdout.write("  Context-Aware (с учётом погоды и шин):")

        from analytics.context.train import train_context_model_by_class

        # Обучаем контекстную модель
        ratings_by_class, weights_by_class = train_context_model_by_class(
            data_loader=loader,
            entity_type='driver',
            alpha=alpha
        )

        with transaction.atomic():
            for class_id, ratings in ratings_by_class.items():
                self.stdout.write(f"    Класс ID {class_id}...")

                # Показываем веса контекста для этого класса
                if class_id in weights_by_class:
                    w = weights_by_class[class_id]
                    self.stdout.write(f"      Веса: temp={w[0]:.3f}, precip={w[1]:.3f}, "
                                     f"tyre={w[2]:.3f}, track={w[3]:.3f}")

                for driver_id, score in ratings.items():
                    try:
                        driver = Driver.objects.get(id=driver_id)

                        if not driver.context_by_class:
                            driver.context_by_class = {}

                        # Получаем количество стартов
                        starts = 0
                        if str(class_id) in driver.rating_by_class:
                            starts = driver.rating_by_class[str(class_id)].get('starts', 0)

                        driver.context_by_class[str(class_id)] = {
                            'score': float(score),
                            'starts': starts,
                            'updated': timezone.now().isoformat()
                        }

                        # Сохраняем веса контекста (один раз на класс)
                        if class_id in weights_by_class and not driver.context_weights:
                            driver.context_weights = {
                                'temperature': float(weights_by_class[class_id][0]),
                                'precipitation': float(weights_by_class[class_id][1]),
                                'tyre': float(weights_by_class[class_id][2]),
                                'track': float(weights_by_class[class_id][3]),
                            }

                        driver.save()
                    except Driver.DoesNotExist:
                        continue

                self.stdout.write(f"      Обновлено {len(ratings)} пилотов")

    def _update_chassis_ratings(self, loader, model_type, alpha, damping, min_starts):
        """Обновляет рейтинги шасси."""
        self.stdout.write("\n=== ШАССИ ===")

        if model_type in ['bt', 'all']:
            self._update_chassis_bt_ratings(loader, alpha, min_starts)

        if model_type in ['pr', 'all']:
            self._update_chassis_pr_ratings(loader, damping)

        # Для шасси тоже можно добавить контекстную модель позже

    def _update_chassis_bt_ratings(self, loader, alpha, min_starts):
        """Обновляет рейтинги шасси по модели Брэдли-Терри."""
        self.stdout.write("  Брэдли-Терри:")

        df_comparisons = loader.create_pairwise_comparisons('chassis')

        if len(df_comparisons) == 0:
            self.stdout.write("    Нет данных")
            return

        model = BradleyTerryLasso(alpha=alpha)
        model.fit(df_comparisons)

        ratings = model.get_all_ratings()

        with transaction.atomic():
            for chassis_id, score in ratings.items():
                Chassis.objects.filter(id=chassis_id).update(
                    rating_score=score,
                    rating_updated_at=timezone.now()
                )

        self.stdout.write(f"    Обновлено {len(ratings)} шасси")

    def _update_chassis_pr_ratings(self, loader, damping):
        """Обновляет рейтинги шасси по модели PageRank."""
        self.stdout.write("  PageRank:")

        df_comparisons = loader.create_pairwise_comparisons('chassis')

        if len(df_comparisons) == 0:
            self.stdout.write("    Нет данных")
            return

        model = ModifiedPageRank(damping_factor=damping)
        model.fit(df_comparisons)

        ratings = model.get_all_ratings()

        with transaction.atomic():
            for chassis_id, score in ratings.items():
                Chassis.objects.filter(id=chassis_id).update(
                    pagerank_score=score,
                    pagerank_updated_at=timezone.now()
                )

        self.stdout.write(f"    Обновлено {len(ratings)} шасси")

    def _create_class_comparisons(self, df_class, entity_type):
        """Создает парные сравнения для одного класса."""
        comparisons = []

        for group_id, group in df_class.groupby('group_id'):
            if len(group) < 2:
                continue

            group = group.sort_values('position')

            for i, row_i in group.iterrows():
                for j, row_j in group.iterrows():
                    if i == j:
                        continue

                    if row_i['position'] < row_j['position']:
                        winner_id = row_i[f'{entity_type}_id']
                        loser_id = row_j[f'{entity_type}_id']
                    else:
                        winner_id = row_j[f'{entity_type}_id']
                        loser_id = row_i[f'{entity_type}_id']

                    position_diff = abs(row_i['position'] - row_j['position'])
                    weight = 1.0 / (1.0 + position_diff)

                    comparisons.append({
                        'entity_1_id': winner_id,
                        'entity_2_id': loser_id,
                        'winner_id': winner_id,
                        'loser_id': loser_id,
                        'weight': weight,
                        'group_id': group_id,
                    })

        return pd.DataFrame(comparisons)
