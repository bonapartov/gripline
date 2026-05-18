# -*- coding: utf-8 -*-
"""
Двухэтапная контекстная модель Bradley-Terry.

Этап 1: BT-рейтинги считаются отдельно (стандартной моделью).
Этап 2: Логистическая регрессия на 5 признаках:
        [bt_diff, temperature, precipitation, tyre_id, track_id]
        Это на порядок быстрее одноэтапной модели (5 признаков вместо N_пилотов+4).
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
import logging
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


class ContextAwareBradleyTerry:
    """
    Двухэтапная модель: базовые BT-рейтинги + поправка на контекст.

    P(i beats j | context) = σ(α*(θ_i - θ_j) + β₁*temp + β₂*precip + β₃*tyre + β₄*track)

    Шаг 2 работает только с 5 признаками независимо от числа пилотов.
    """

    def __init__(self, alpha=0.1, max_iter=1000):
        self.alpha = alpha
        self.max_iter = max_iter
        self.bt_coef_ = None        # коэффициент при bt_diff (≈1 в норме)
        self.context_weights_ = None  # [temp, precip, tyre, track]
        self.scaler = StandardScaler()
        self.model = None

    def fit(self, df_comparisons: pd.DataFrame, bt_ratings: Optional[Dict] = None):
        """
        Обучает контекстную модель.

        Args:
            df_comparisons: DataFrame с колонками
                entity_1_id, entity_2_id, winner_id, weight,
                temperature, precipitation, tyre_id, track_id
            bt_ratings: dict {entity_id: score} — предобученные BT-рейтинги.
                        Если None — bt_diff считается нулём для всех пар.
        """
        X_context = []
        X_bt = []
        y = []
        weights = []

        for _, row in df_comparisons.iterrows():
            e1 = row['entity_1_id']
            e2 = row['entity_2_id']
            w = float(row.get('weight', 1.0))

            # BT-разность как смещение
            if bt_ratings:
                bt1 = bt_ratings.get(e1, 0.0)
                bt2 = bt_ratings.get(e2, 0.0)
            else:
                bt1 = bt2 = 0.0
            bt_diff = bt1 - bt2

            # Контекстные признаки
            context = [
                float(row.get('temperature') or 0),
                float(row.get('precipitation') or 0),
                float(row.get('tyre_id') or 0),
                float(row.get('track_id') or 0),
            ]

            X_bt.append(bt_diff)
            X_context.append(context)
            y.append(1)
            weights.append(w)

            # Обратное сравнение
            X_bt.append(-bt_diff)
            X_context.append([-c for c in context])
            y.append(0)
            weights.append(w)

        X_bt = np.array(X_bt).reshape(-1, 1)
        X_context = np.array(X_context)
        y = np.array(y)
        weights = np.array(weights)

        # Нормализуем контекстные признаки
        if np.any(X_context != 0):
            self.scaler.fit(X_context)
            X_context = self.scaler.transform(X_context)

        X = np.hstack([X_bt, X_context])

        self.model = LogisticRegression(
            C=1.0 / self.alpha,
            solver='lbfgs',
            max_iter=self.max_iter,
            fit_intercept=False,
            random_state=42,
        )
        self.model.fit(X, y, sample_weight=weights)

        coefs = self.model.coef_[0]
        self.bt_coef_ = coefs[0]
        self.context_weights_ = coefs[1:]

        logger.info(f"Контекстная модель обучена. bt_coef={self.bt_coef_:.3f}, "
                    f"temp={self.context_weights_[0]:.3f}, "
                    f"precip={self.context_weights_[1]:.3f}, "
                    f"tyre={self.context_weights_[2]:.3f}, "
                    f"track={self.context_weights_[3]:.3f}")
        return self

    def get_all_ratings(self) -> Dict:
        """
        Возвращает пустой словарь — в двухэтапной модели рейтинги пилотов
        берутся из BT, контекстная модель хранит только веса контекста.
        """
        return {}

    def predict_proba(self, entity_1_id, entity_2_id, bt_ratings=None, context=None) -> float:
        """
        Предсказывает вероятность победы с учётом BT-рейтингов и контекста.
        """
        if self.model is None:
            raise ValueError("Модель не обучена")

        bt1 = bt_ratings.get(entity_1_id, 0.0) if bt_ratings else 0.0
        bt2 = bt_ratings.get(entity_2_id, 0.0) if bt_ratings else 0.0
        bt_diff = bt1 - bt2

        context_vec = [0.0, 0.0, 0.0, 0.0]
        if context:
            context_vec = [
                float(context.get('temperature', 0) or 0),
                float(context.get('precipitation', 0) or 0),
                float(context.get('tyre_id', 0) or 0),
                float(context.get('track_id', 0) or 0),
            ]
            if np.any(np.array(context_vec) != 0):
                context_vec = self.scaler.transform([context_vec])[0].tolist()

        x = np.array([[bt_diff] + context_vec])
        return float(self.model.predict_proba(x)[0][1])
