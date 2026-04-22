# -*- coding: utf-8 -*-
"""
Обучение мультимодальной модели для разных классов.
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple

from analytics.context.weather_model import ContextAwareBradleyTerry
from analytics.core.data_loader import DataLoader

logger = logging.getLogger(__name__)


def train_context_model_by_class(
    data_loader: DataLoader,
    entity_type: str = 'driver',
    alpha: float = 0.1
) -> Tuple[Dict[int, Dict[int, float]], Dict[int, np.ndarray]]:
    """
    Обучает контекстную модель для каждого класса отдельно.

    Args:
        data_loader: загрузчик данных
        entity_type: 'driver' или 'chassis'
        alpha: коэффициент регуляризации

    Returns:
        tuple: (ratings_by_class, context_weights_by_class)
    """
    from website.models import RaceClass

    df_races = data_loader.df_races
    if df_races is None:
        data_loader.load_all_data()
        df_races = data_loader.df_races

    classes = RaceClass.objects.all()

    ratings_by_class = {}
    weights_by_class = {}

    for race_class in classes:
        class_id = race_class.id
        logger.info(f"Обучение контекстной модели для класса {race_class.name} (ID: {class_id})")

        # Фильтруем данные по классу
        df_class = df_races[df_races['class_id'] == class_id].copy()

        if len(df_class) < 10:
            logger.info(f"  Недостаточно данных для класса {class_id}")
            continue

        # Создаём контекстные сравнения
        comparisons = []

        for group_id, group in df_class.groupby('group_id'):
            if len(group) < 2:
                continue

            group = group.sort_values('position')

            # Контекст для группы с обработкой пропусков
            temp = group['temperature'].iloc[0] if 'temperature' in group.columns else 0
            if pd.isna(temp):
                temp = 0.0

            precip = group['precipitation'].iloc[0] if 'precipitation' in group.columns else 0
            if pd.isna(precip):
                precip = 0.0

            tyre = group['tyre_id'].iloc[0] if 'tyre_id' in group.columns else 0
            if pd.isna(tyre):
                tyre = 0

            track = group['track_id'].iloc[0] if 'track_id' in group.columns else 0
            if pd.isna(track):
                track = 0

            for i, row_i in group.iterrows():
                for j, row_j in group.iterrows():
                    if i == j:
                        continue

                    if row_i['position'] < row_j['position']:
                        winner = row_i[f'{entity_type}_id']
                        loser = row_j[f'{entity_type}_id']
                    else:
                        winner = row_j[f'{entity_type}_id']
                        loser = row_i[f'{entity_type}_id']

                    pos_diff = abs(row_i['position'] - row_j['position'])
                    weight = 1.0 / (1.0 + pos_diff)

                    comparisons.append({
                        'entity_1_id': winner,
                        'entity_2_id': loser,
                        'winner_id': winner,
                        'loser_id': loser,
                        'weight': weight,
                        'temperature': temp,
                        'precipitation': precip,
                        'tyre_id': tyre,
                        'track_id': track,
                    })

        if len(comparisons) < 20:
            logger.info(f"  Недостаточно сравнений для класса {class_id}")
            continue

        df_comp = pd.DataFrame(comparisons)
        # Убеждаемся, что нет NaN перед обучением
        df_comp = df_comp.fillna(0)
        logger.info(f"  Создано {len(df_comp)} сравнений")

        # Обучаем модель
        model = ContextAwareBradleyTerry(alpha=alpha)
        model.fit(df_comp)

        # Сохраняем результаты
        ratings = model.get_all_ratings()
        ratings_by_class[class_id] = ratings

        if model.context_weights_ is not None:
            weights_by_class[class_id] = model.context_weights_
            logger.info(f"  Веса контекста: temp={model.context_weights_[0]:.3f}, "
                       f"precip={model.context_weights_[1]:.3f}, "
                       f"tyre={model.context_weights_[2]:.3f}, "
                       f"track={model.context_weights_[3]:.3f}")

        logger.info(f"  Получено рейтингов: {len(ratings)}")

    return ratings_by_class, weights_by_class
