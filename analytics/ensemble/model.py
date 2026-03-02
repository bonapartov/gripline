# -*- coding: utf-8 -*-
"""
Ансамбль моделей для ранжирования.
Комбинирует Брэдли-Терри и PageRank для получения более точных прогнозов.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
import logging
from scipy.optimize import minimize
from sklearn.metrics import accuracy_score, log_loss

logger = logging.getLogger(__name__)


class EnsembleRanking:
    """
    Ансамбль моделей ранжирования.

    Поддерживает:
    - Взвешенное голосование моделей
    - Оптимизацию весов на исторических данных
    - Расчёт комбинированного рейтинга
    """

    def __init__(self, models: Dict[str, object] = None):
        """
        Args:
            models: словарь {название_модели: объект_модели}
        """
        self.models = models or {}
        self.weights = {name: 1.0 / len(self.models) for name in self.models} if models else {}
        self.combined_ratings_ = None
        self.entity_to_idx_ = None
        self.idx_to_entity_ = None

    def add_model(self, name: str, model: object):
        """Добавляет модель в ансамбль."""
        self.models[name] = model
        # При добавлении новой модели перераспределяем веса равномерно
        n_models = len(self.models)
        self.weights = {name: 1.0 / n_models for name in self.models}

    def set_weights(self, weights: Dict[str, float]):
        """Устанавливает веса для моделей вручную."""
        # Нормализуем веса
        total = sum(weights.values())
        self.weights = {name: w / total for name, w in weights.items()}
        logger.info(f"Установлены веса: {self.weights}")

    def _prepare_entity_mapping(self, all_ratings: Dict[str, Dict[int, float]]):
        """
        Создаёт единый маппинг для всех сущностей из разных моделей.

        Args:
            all_ratings: словарь {model_name: {entity_id: rating}}
        """
        # Собираем все ID сущностей из всех моделей
        all_entities = set()
        for ratings in all_ratings.values():
            all_entities.update(ratings.keys())

        self.entity_to_idx_ = {e: i for i, e in enumerate(sorted(all_entities))}
        self.idx_to_entity_ = {i: e for e, i in self.entity_to_idx_.items()}

    def combine_ratings(self, all_ratings: Dict[str, Dict[int, float]]) -> Dict[int, float]:
        """
        Комбинирует рейтинги из разных моделей с текущими весами.

        Args:
            all_ratings: словарь {model_name: {entity_id: rating}}

        Returns:
            словарь {entity_id: combined_rating}
        """
        self._prepare_entity_mapping(all_ratings)

        # Нормализуем рейтинги каждой модели в диапазон [0, 1]
        normalized = {}
        for model_name, ratings in all_ratings.items():
            values = np.array(list(ratings.values()))
            if values.max() > values.min():
                norm_values = (values - values.min()) / (values.max() - values.min())
            else:
                norm_values = np.zeros_like(values)

            normalized[model_name] = dict(zip(ratings.keys(), norm_values))

        # Комбинируем с весами
        combined = {}
        for entity_id in self.entity_to_idx_:
            score = 0.0
            total_weight = 0.0

            for model_name, ratings in normalized.items():
                if entity_id in ratings:
                    weight = self.weights.get(model_name, 0)
                    score += weight * ratings[entity_id]
                    total_weight += weight

            combined[entity_id] = score / total_weight if total_weight > 0 else 0.0

        self.combined_ratings_ = combined
        return combined

    def optimize_weights(self,
                         all_ratings: Dict[str, Dict[int, float]],
                         df_comparisons: pd.DataFrame,
                         method: str = 'accuracy') -> Dict[str, float]:
        """
        Оптимизирует веса моделей для максимизации точности предсказаний.

        Args:
            all_ratings: словарь {model_name: {entity_id: rating}}
            df_comparisons: DataFrame с реальными сравнениями
            method: 'accuracy' или 'log_loss'

        Returns:
            оптимальные веса
        """
        n_models = len(all_ratings)
        model_names = list(all_ratings.keys())

        def objective(weights):
            # Нормализуем веса
            weights = np.abs(weights)
            weights = weights / weights.sum()

            # Устанавливаем временные веса
            temp_weights = dict(zip(model_names, weights))
            self.weights = temp_weights

            # Получаем комбинированные рейтинги
            combined = self.combine_ratings(all_ratings)

            # Предсказываем исходы сравнений
            y_true = []
            y_pred = []

            for _, row in df_comparisons.iterrows():
                ent1 = row['entity_1_id']
                ent2 = row['entity_2_id']

                if ent1 in combined and ent2 in combined:
                    # Вероятность победы 1 над 2 пропорциональна разности рейтингов
                    prob = 1.0 / (1.0 + np.exp(combined[ent2] - combined[ent1]))

                    y_pred.append(prob)
                    y_true.append(1 if row['winner_id'] == ent1 else 0)

            if not y_pred:
                return 1.0

            if method == 'accuracy':
                # Минимизируем ошибку (1 - accuracy)
                pred_binary = [1 if p > 0.5 else 0 for p in y_pred]
                accuracy = accuracy_score(y_true, pred_binary)
                return 1.0 - accuracy
            else:
                # Минимизируем log loss
                return log_loss(y_true, y_pred)

        # Начальное приближение - равные веса
        x0 = np.ones(n_models) / n_models

        # Оптимизация
        result = minimize(
            objective,
            x0,
            method='SLSQP',
            bounds=[(0, 1) for _ in range(n_models)],
            constraints={'type': 'eq', 'fun': lambda x: np.sum(x) - 1}
        )

        if result.success:
            optimal_weights = dict(zip(model_names, result.x))
            logger.info(f"Найдены оптимальные веса: {optimal_weights}")
            return optimal_weights
        else:
            logger.warning(f"Оптимизация не удалась: {result.message}")
            return dict(zip(model_names, x0))

    def predict_match(self, entity1_id: int, entity2_id: int) -> float:
        """
        Предсказывает вероятность победы entity1 над entity2.

        Returns:
            вероятность от 0 до 1
        """
        if self.combined_ratings_ is None:
            raise ValueError("Сначала выполните combine_ratings()")

        if entity1_id not in self.combined_ratings_ or entity2_id not in self.combined_ratings_:
            return 0.5

        r1 = self.combined_ratings_[entity1_id]
        r2 = self.combined_ratings_[entity2_id]

        return 1.0 / (1.0 + np.exp(r2 - r1))

    def get_rating(self, entity_id: int) -> float:
        """Возвращает комбинированный рейтинг сущности."""
        if self.combined_ratings_ is None:
            raise ValueError("Сначала выполните combine_ratings()")

        return self.combined_ratings_.get(entity_id, 0.0)

    def get_all_ratings(self) -> Dict[int, float]:
        """Возвращает все комбинированные рейтинги."""
        if self.combined_ratings_ is None:
            raise ValueError("Сначала выполните combine_ratings()")

        return self.combined_ratings_
