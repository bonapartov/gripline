# -*- coding: utf-8 -*-
"""
Модуль для оценки качества моделей.
Содержит метрики и функции сравнения.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class ModelEvaluator:
    """
    Класс для оценки качества моделей ранжирования.
    """

    def __init__(self):
        self.metrics = {}

    def evaluate_pairwise(
        self,
        y_true: List[Tuple[int, int]],
        y_pred_proba: List[float]
    ) -> Dict:
        """
        Оценивает качество предсказаний парных сравнений.

        Args:
            y_true: список кортежей (winner_id, loser_id)
            y_pred_proba: вероятности победы первого над вторым

        Returns:
            Словарь с метриками
        """
        # Преобразуем вероятности в бинарные предсказания
        y_pred_binary = [1 if p > 0.5 else 0 for p in y_pred_proba]

        metrics = {
            'accuracy': accuracy_score([1] * len(y_true), y_pred_binary),
            'log_loss': log_loss([1] * len(y_true), y_pred_proba),
        }

        logger.info(f"Pairwise evaluation: accuracy={metrics['accuracy']:.3f}")
        return metrics

    def evaluate_rankings(
        self,
        true_rankings: Dict[int, float],
        pred_rankings: Dict[int, float]
    ) -> Dict:
        """
        Сравнивает два рейтинга (например, истинный и предсказанный).

        Args:
            true_rankings: словарь {id: истинное значение}
            pred_rankings: словарь {id: предсказанное значение}

        Returns:
            Словарь с метриками
        """
        # Находим общие ID
        common_ids = set(true_rankings.keys()) & set(pred_rankings.keys())

        if not common_ids:
            return {'error': 'No common entities'}

        true_values = [true_rankings[id_] for id_ in common_ids]
        pred_values = [pred_rankings[id_] for id_ in common_ids]

        # Вычисляем корреляцию Спирмена (ранговая корреляция)
        from scipy.stats import spearmanr
        corr, p_value = spearmanr(true_values, pred_values)

        metrics = {
            'spearman_correlation': corr,
            'p_value': p_value,
            'mae': mean_absolute_error(true_values, pred_values),
            'n_entities': len(common_ids)
        }

        logger.info(f"Ranking evaluation: Spearman={corr:.3f}, MAE={metrics['mae']:.3f}")
        return metrics

    def cross_validate(self, model, df_comparisons, n_folds=5):
        """
        Кросс-валидация модели на парных сравнениях.

        Args:
            model: модель с методами fit и predict_proba
            df_comparisons: DataFrame с колонками entity_1, entity_2, winner
            n_folds: количество фолдов

        Returns:
            Словарь с усредненными метриками
        """
        from sklearn.model_selection import KFold

        kf = KFold(n_splits=n_folds, shuffle=True, random_state=42)
        fold_metrics = []

        for fold, (train_idx, test_idx) in enumerate(kf.split(df_comparisons)):
            train_data = df_comparisons.iloc[train_idx]
            test_data = df_comparisons.iloc[test_idx]

            # Обучаем модель
            model.fit(train_data)

            # Предсказываем
            y_pred = []
            y_true = []

            for _, row in test_data.iterrows():
                prob = model.predict_proba(row['entity_1_id'], row['entity_2_id'])
                y_pred.append(prob)
                y_true.append(1 if row['winner_id'] == row['entity_1_id'] else 0)

            # Оцениваем
            fold_metrics.append({
                'fold': fold,
                'accuracy': accuracy_score(y_true, [1 if p > 0.5 else 0 for p in y_pred]),
                'log_loss': log_loss(y_true, y_pred)
            })

        # Усредняем
        avg_metrics = {
            'accuracy_mean': np.mean([m['accuracy'] for m in fold_metrics]),
            'accuracy_std': np.std([m['accuracy'] for m in fold_metrics]),
            'log_loss_mean': np.mean([m['log_loss'] for m in fold_metrics]),
            'log_loss_std': np.std([m['log_loss'] for m in fold_metrics])
        }

        logger.info(f"Cross-validation: accuracy={avg_metrics['accuracy_mean']:.3f}±{avg_metrics['accuracy_std']:.3f}")
        return avg_metrics
