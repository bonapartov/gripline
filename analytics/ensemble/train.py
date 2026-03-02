# -*- coding: utf-8 -*-
"""
Обучение ансамбля моделей для разных классов.
"""

import pandas as pd
import logging
from typing import Dict, List, Optional, Tuple

from analytics.ensemble.model import EnsembleRanking
from analytics.core.data_loader import DataLoader

logger = logging.getLogger(__name__)


def calculate_ensemble_by_class(
    data_loader: DataLoader,
    bt_ratings: Dict[int, Dict[int, float]],
    pr_ratings: Dict[int, Dict[int, float]],
    optimize: bool = True
) -> Tuple[Dict[int, Dict[int, float]], Dict[int, Dict[str, float]]]:
    """
    Рассчитывает ансамбль Брэдли-Терри и PageRank для каждого класса.

    Args:
        data_loader: загрузчик данных
        bt_ratings: словарь {class_id: {driver_id: rating}}
        pr_ratings: словарь {class_id: {driver_id: rating}}
        optimize: если True, оптимизировать веса, иначе использовать равные

    Returns:
        tuple: (ensemble_ratings, optimal_weights_by_class)
    """
    from website.models import RaceClass

    classes = RaceClass.objects.all()

    ensemble_results = {}
    weights_by_class = {}

    for race_class in classes:
        class_id = race_class.id
        logger.info(f"Расчет ансамбля для класса {race_class.name} (ID: {class_id})")

        # Получаем рейтинги для этого класса
        bt = bt_ratings.get(class_id, {})
        pr = pr_ratings.get(class_id, {})

        if not bt or not pr:
            logger.info(f"  Недостаточно данных для класса {class_id}")
            continue

        # Находим общих пилотов
        common_drivers = set(bt.keys()) & set(pr.keys())

        if len(common_drivers) < 3:
            logger.info(f"  Мало общих пилотов для класса {class_id}")
            continue

        # Создаем словарь рейтингов только для общих пилотов
        bt_common = {d: bt[d] for d in common_drivers}
        pr_common = {d: pr[d] for d in common_drivers}

        all_ratings = {
            'bradley_terry': bt_common,
            'pagerank': pr_common
        }

        # Создаем ансамбль
        ensemble = EnsembleRanking()

        if optimize:
            # Создаем данные для оптимизации
            # Для этого используем парные сравнения из data_loader
            df_class = data_loader.df_races[data_loader.df_races['class_id'] == class_id].copy()

            if len(df_class) >= 10:
                # Создаем парные сравнения
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
                                winner_id = row_i['driver_id']
                                loser_id = row_j['driver_id']
                            else:
                                winner_id = row_j['driver_id']
                                loser_id = row_i['driver_id']

                            comparisons.append({
                                'entity_1_id': winner_id,
                                'entity_2_id': loser_id,
                                'winner_id': winner_id,
                                'loser_id': loser_id,
                                'group_id': group_id,
                            })

                df_comparisons = pd.DataFrame(comparisons)

                # Оптимизируем веса
                weights = ensemble.optimize_weights(all_ratings, df_comparisons)
                weights_by_class[class_id] = weights
            else:
                # Если мало данных, используем равные веса
                ensemble.set_weights({'bradley_terry': 0.5, 'pagerank': 0.5})
                weights_by_class[class_id] = {'bradley_terry': 0.5, 'pagerank': 0.5}
        else:
            # Равные веса
            ensemble.set_weights({'bradley_terry': 0.5, 'pagerank': 0.5})
            weights_by_class[class_id] = {'bradley_terry': 0.5, 'pagerank': 0.5}

        # Комбинируем рейтинги
        combined = ensemble.combine_ratings(all_ratings)
        ensemble_results[class_id] = combined

        logger.info(f"  Получено рейтингов: {len(combined)}")
        logger.info(f"  Веса: {weights_by_class[class_id]}")

    return ensemble_results, weights_by_class
