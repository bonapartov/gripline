# -*- coding: utf-8 -*-
"""
Обучение модели PageRank для разных сущностей.
"""

import pandas as pd
import logging
from typing import Dict, List, Optional

from analytics.pagerank.model import ModifiedPageRank
from analytics.core.data_loader import DataLoader

logger = logging.getLogger(__name__)


def calculate_pagerank_by_class(
    data_loader: DataLoader,
    entity_type: str = 'driver',
    damping: float = 0.85
) -> Dict[int, Dict[int, float]]:
    """
    Рассчитывает PageRank для каждой сущности отдельно по классам.

    Args:
        data_loader: загрузчик данных
        entity_type: 'driver' или 'chassis'
        damping: демпфирующий фактор PageRank

    Returns:
        словарь {class_id: {entity_id: pagerank_score}}
    """
    from website.models import RaceClass

    df_races = data_loader.df_races
    if df_races is None:
        data_loader.load_all_data()
        df_races = data_loader.df_races

    # Получаем все классы
    classes = RaceClass.objects.all()

    results_by_class = {}

    for race_class in classes:
        class_id = race_class.id
        logger.info(f"Расчет PageRank для класса {race_class.name} (ID: {class_id})")

        # Фильтруем данные по классу
        df_class = df_races[df_races['class_id'] == class_id].copy()

        if len(df_class) < 5:
            logger.info(f"  Недостаточно данных для класса {class_id}, пропускаем")
            continue

        # Создаем парные сравнения для этого класса
        comparisons = []

        for group_id, group in df_class.groupby('group_id'):
            if len(group) < 2:
                continue

            group = group.sort_values('position')

            for i, row_i in group.iterrows():
                for j, row_j in group.iterrows():
                    if i == j:
                        continue

                    # Победитель тот, у кого меньше позиция
                    if row_i['position'] < row_j['position']:
                        winner_id = row_i[f'{entity_type}_id']
                        loser_id = row_j[f'{entity_type}_id']
                    else:
                        winner_id = row_j[f'{entity_type}_id']
                        loser_id = row_i[f'{entity_type}_id']

                    # Вес = обратная разница в позициях
                    position_diff = abs(row_i['position'] - row_j['position'])
                    weight = 1.0 / (1.0 + position_diff)

                    comparisons.append({
                        'entity_1_id': winner_id,
                        'entity_2_id': loser_id,
                        'weight': weight,
                        'group_id': group_id,
                    })

        if len(comparisons) < 10:
            logger.info(f"  Недостаточно сравнений для класса {class_id}")
            continue

        df_comparisons = pd.DataFrame(comparisons)
        logger.info(f"  Создано {len(df_comparisons)} парных сравнений")

        # Обучаем PageRank
        model = ModifiedPageRank(damping_factor=damping)
        model.fit(df_comparisons)

        # Получаем рейтинги
        ratings = model.get_all_ratings()

        # Нормируем для удобства (можно не нормировать, но для сравнения полезно)
        # Здесь просто сохраняем как есть, нормировка будет на уровне отображения

        results_by_class[class_id] = ratings
        logger.info(f"  Получено рейтингов: {len(ratings)}")

    return results_by_class
