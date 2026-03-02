# -*- coding: utf-8 -*-
"""
Мультимодальная модель ранжирования с учётом внешних факторов.
Учитывает:
- температуру
- осадки
- тип шин
- трассу
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
import logging
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


class ContextAwareBradleyTerry:
    """
    Модель Брэдли-Терри с учётом контекстных факторов.

    Расширяет базовую модель добавлением ковариат:
    θ_i(context) = θ_i + β₁*temp + β₂*rain + β₃*tyre + β₄*track
    """

    def __init__(self, alpha=0.1, max_iter=1000):
        self.alpha = alpha
        self.max_iter = max_iter
        self.ratings_ = None
        self.context_weights_ = None
        self.entity_to_idx_ = None
        self.idx_to_entity_ = None
        self.scaler = StandardScaler()

    def _prepare_features(self, df_comparisons: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Подготавливает признаки для модели.

        Для каждого сравнения i vs j создаёт вектор:
        [разность рейтингов, температура, осадки, шины, трасса]
        """
        # Маппинг сущностей
        all_entities = pd.unique(
            df_comparisons[['entity_1_id', 'entity_2_id']].values.ravel()
        )
        self.entity_to_idx_ = {e: i for i, e in enumerate(all_entities)}
        self.idx_to_entity_ = {i: e for e, i in self.entity_to_idx_.items()}
        n_entities = len(all_entities)

        X = []
        y = []
        weights = []

        for _, row in df_comparisons.iterrows():
            i = self.entity_to_idx_[row['entity_1_id']]
            j = self.entity_to_idx_[row['entity_2_id']]
            w = row.get('weight', 1.0)

            # Базовый вектор для рейтингов (как в обычном BT)
            x_base = np.zeros(n_entities)
            x_base[i] = 1
            x_base[j] = -1

            # Контекстные признаки с обработкой None
            context = []
            for val in [
                row.get('temperature'),
                row.get('precipitation'),
                row.get('tyre_id'),
                row.get('track_id')
            ]:
                if val is None:
                    context.append(0.0)
                else:
                    context.append(float(val))

            # Объединяем
            x = np.concatenate([x_base, context])
            X.append(x)
            y.append(1)  # победа i
            weights.append(w)

            # Обратное сравнение с противоположными контекстными знаками
            x_base_inv = np.zeros(n_entities)
            x_base_inv[j] = 1
            x_base_inv[i] = -1
            x_inv = np.concatenate([x_base_inv, [-c for c in context]])
            X.append(x_inv)
            y.append(0)
            weights.append(w)

        X = np.array(X)
        y = np.array(y)
        weights = np.array(weights)

        # Нормализуем контекстные признаки
        if X.shape[1] > n_entities:
            context_start = n_entities
            # Проверяем, что есть хотя бы одно ненулевое значение
            if np.any(X[:, context_start:] != 0):
                self.scaler.fit(X[:, context_start:])
                X[:, context_start:] = self.scaler.transform(X[:, context_start:])

        return X, y, weights

    def fit(self, df_comparisons: pd.DataFrame):
        """
        Обучает модель на данных с учётом контекста.
        """
        X, y, weights = self._prepare_features(df_comparisons)

        # Обучаем логистическую регрессию
        self.model = LogisticRegression(
            penalty='l1',
            C=1.0 / self.alpha,
            solver='saga',
            max_iter=self.max_iter,
            fit_intercept=False,
            random_state=42
        )

        self.model.fit(X, y, sample_weight=weights)

        # Разделяем коэффициенты на рейтинги и контекстные веса
        n_entities = len(self.entity_to_idx_)
        self.ratings_ = self.model.coef_[0][:n_entities]
        if X.shape[1] > n_entities:
            self.context_weights_ = self.model.coef_[0][n_entities:]

        logger.info(f"Модель обучена. Число сущностей: {n_entities}")
        if self.context_weights_ is not None:
            logger.info(f"Веса контекста: temp={self.context_weights_[0]:.3f}, "
                       f"rain={self.context_weights_[1]:.3f}, "
                       f"tyre={self.context_weights_[2]:.3f}, "
                       f"track={self.context_weights_[3]:.3f}")

        return self

    def predict_proba(self, entity_1_id, entity_2_id, context=None) -> float:
        """
        Предсказывает вероятность победы с учётом контекста.

        Args:
            entity_1_id, entity_2_id: ID пилотов/шасси
            context: dict с {'temperature', 'precipitation', 'tyre_id', 'track_id'}
        """
        if self.ratings_ is None:
            raise ValueError("Модель не обучена")

        if entity_1_id not in self.entity_to_idx_:
            return 0.5
        if entity_2_id not in self.entity_to_idx_:
            return 0.5

        i = self.entity_to_idx_[entity_1_id]
        j = self.entity_to_idx_[entity_2_id]

        # Базовая разность рейтингов
        rating_diff = self.ratings_[i] - self.ratings_[j]

        # Добавляем контекст
        if context and self.context_weights_ is not None:
            context_vector = [
                context.get('temperature', 0),
                context.get('precipitation', 0),
                context.get('tyre_id', 0),
                context.get('track_id', 0),
            ]
            # Нормализуем
            context_vector = self.scaler.transform([context_vector])[0]
            context_effect = np.dot(self.context_weights_, context_vector)
            rating_diff += context_effect

        return 1.0 / (1.0 + np.exp(-rating_diff))

    def get_rating(self, entity_id) -> float:
        """Возвращает базовый рейтинг сущности."""
        if self.ratings_ is None:
            raise ValueError("Модель не обучена")
        if entity_id not in self.entity_to_idx_:
            return 0.0
        return float(self.ratings_[self.entity_to_idx_[entity_id]])

    def get_all_ratings(self) -> Dict[int, float]:
        """Возвращает все базовые рейтинги."""
        if self.ratings_ is None:
            raise ValueError("Модель не обучена")
        return {
            self.idx_to_entity_[i]: float(self.ratings_[i])
            for i in range(len(self.ratings_))
        }
