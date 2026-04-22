# -*- coding: utf-8 -*-
"""
Модель Брэдли-Терри с Lasso-регуляризацией.
Основана на работе: "A Lasso-based Bradley–Terry model for ranking"
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class BradleyTerryLasso:
    """
    Модель Брэдли-Терри с Lasso-штрафом для ранжирования.

    Формула: P(i beats j) = exp(θ_i) / (exp(θ_i) + exp(θ_j))
    где θ — рейтинг сущности.

    Lasso-штраф заставляет схожие сущности иметь близкие рейтинги.
    """

    def __init__(self, alpha=0.1, max_iter=1000):
        """
        Args:
            alpha: коэффициент L1-регуляризации
            max_iter: максимальное число итераций
        """
        self.alpha = alpha
        self.max_iter = max_iter
        self.ratings_ = None
        self.entity_to_idx_ = None
        self.idx_to_entity_ = None
        self.model = None

    def _prepare_data(self, df_comparisons: pd.DataFrame):
        """
        Преобразует данные в формат для логистической регрессии.

        Каждое сравнение i vs j превращается в ДВЕ строки:
        - победа i над j: X[i] - X[j] = 1, y = 1
        - победа j над i: X[j] - X[i] = 1, y = 0 (или можно с весом)
        """
        # Создаем маппинг сущностей в индексы
        all_entities = pd.unique(
            df_comparisons[['entity_1_id', 'entity_2_id']].values.ravel()
        )
        self.entity_to_idx_ = {e: i for i, e in enumerate(all_entities)}
        self.idx_to_entity_ = {i: e for e, i in self.entity_to_idx_.items()}
        n_entities = len(all_entities)

        # Создаем матрицу X и вектор y
        X = []
        y = []
        weights = []

        for _, row in df_comparisons.iterrows():
            i = self.entity_to_idx_[row['entity_1_id']]
            j = self.entity_to_idx_[row['entity_2_id']]
            w = row.get('weight', 1.0)

            # Прямое сравнение (победа i над j)
            x_ij = np.zeros(n_entities)
            x_ij[i] = 1
            x_ij[j] = -1
            X.append(x_ij)
            y.append(1)  # победа i
            weights.append(w)

            # Обратное сравнение (победа j над i)
            x_ji = np.zeros(n_entities)
            x_ji[j] = 1
            x_ji[i] = -1
            X.append(x_ji)
            y.append(0)  # поражение i (победа j)
            weights.append(w)  # можно взять тот же вес или меньший

        X = np.array(X)
        y = np.array(y)
        weights = np.array(weights)

        logger.info(f"Подготовлено {len(X)} примеров для обучения")
        return X, y, weights

    def fit(self, df_comparisons: pd.DataFrame):
        """
        Обучает модель на данных парных сравнений.

        Args:
            df_comparisons: DataFrame с колонками
                entity_1_id, entity_2_id, winner_id, [weight]
        """
        X, y, weights = self._prepare_data(df_comparisons)

        # Проверяем, что есть оба класса
        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            logger.warning(f"В данных только один класс: {unique_classes}. Добавляем искусственный контрпример.")
            # Добавляем один искусственный пример с обратным знаком
            X_extra = -X[0:1]  # инвертируем первый пример
            y_extra = np.array([0])
            weights_extra = np.array([weights[0] * 0.1])  # маленький вес

            X = np.vstack([X, X_extra])
            y = np.concatenate([y, y_extra])
            weights = np.concatenate([weights, weights_extra])

        # Обучаем логистическую регрессию с L1-штрафом
        from sklearn.linear_model import LogisticRegression

        self.model = LogisticRegression(
            penalty='l1',
            C=1.0 / self.alpha,  # обратная alpha
            solver='saga',
            max_iter=self.max_iter,
            fit_intercept=False,
            random_state=42,  # для воспроизводимости
            warm_start=False   # убираем warm_start
        )

        self.model.fit(X, y, sample_weight=weights)

        # Коэффициенты и есть наши рейтинги θ
        self.ratings_ = self.model.coef_[0]

        logger.info(f"Модель обучена. Число сущностей: {len(self.ratings_)}")
        return self

    def predict_proba(self, entity_1_id, entity_2_id) -> float:
        """
        Возвращает вероятность победы entity_1 над entity_2.

        P(1 beats 2) = exp(θ₁) / (exp(θ₁) + exp(θ₂))
        """
        if self.ratings_ is None:
            raise ValueError("Модель не обучена")

        if entity_1_id not in self.entity_to_idx_:
            return 0.5  # для новых сущностей

        if entity_2_id not in self.entity_to_idx_:
            return 0.5

        i = self.entity_to_idx_[entity_1_id]
        j = self.entity_to_idx_[entity_2_id]

        exp_i = np.exp(self.ratings_[i])
        exp_j = np.exp(self.ratings_[j])

        return exp_i / (exp_i + exp_j)

    def get_rating(self, entity_id) -> float:
        """Возвращает рейтинг сущности."""
        if self.ratings_ is None:
            raise ValueError("Модель не обучена")

        if entity_id not in self.entity_to_idx_:
            return 0.0

        return self.ratings_[self.entity_to_idx_[entity_id]]

    def get_all_ratings(self) -> Dict[int, float]:
        """Возвращает словарь {id: рейтинг} для всех сущностей."""
        if self.ratings_ is None:
            raise ValueError("Модель не обучена")

        return {
            self.idx_to_entity_[i]: float(self.ratings_[i])
            for i in range(len(self.ratings_))
        }
    def get_class_average(self, class_id, all_ratings, min_starts=5):
        """
        Возвращает средний рейтинг для класса на основе пилотов с достаточным числом стартов
        """
        relevant_ratings = [
            r for r in all_ratings.values()
            if r.get('class_id') == class_id and r.get('starts', 0) >= min_starts
        ]
        if relevant_ratings:
            return sum(r['score'] for r in relevant_ratings) / len(relevant_ratings)
        return 50.0  # если нет данных, возвращаем среднее по умолчанию
