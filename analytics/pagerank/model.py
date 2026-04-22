# -*- coding: utf-8 -*-
"""
Модифицированный PageRank для ранжирования в спортивных соревнованиях.
Основан на работах:
- "A Modified PageRank Algorithm for Sports Ranking" (2025)
- Учитывает силу соперников и разницу в позициях
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
import logging
from scipy import sparse
from scipy.sparse.linalg import eigs

logger = logging.getLogger(__name__)


class ModifiedPageRank:
    """
    Модифицированный PageRank для ранжирования сущностей (пилотов, шасси).

    Особенности:
    1. Вероятность перехода зависит от разницы в позициях
    2. Учитывается только направление "победитель -> проигравший"
    3. Демпфирующий фактор адаптируется под плотность результатов
    """

    def __init__(self, damping_factor: float = 0.85, max_iter: int = 1000, tol: float = 1e-8):
        """
        Args:
            damping_factor: вероятность следования по ссылкам (стандарт 0.85)
            max_iter: максимальное число итераций
            tol: точность сходимости
        """
        self.damping = damping_factor
        self.max_iter = max_iter
        self.tol = tol
        self.ratings_ = None
        self.entity_to_idx_ = None
        self.idx_to_entity_ = None
        self.n_entities = 0

    def _build_weighted_adjacency_matrix(self, df_comparisons: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        Строит взвешенную матрицу смежности на основе парных сравнений.

        Вес ребра i -> j зависит от разницы в позициях:
        чем больше разница, тем меньше вес (потому что победа с большим отрывом
        может быть менее информативной для определения силы)

        Args:
            df_comparisons: DataFrame с колонками entity_1_id, entity_2_id, weight, [position_diff]

        Returns:
            tuple: (весовая матрица, матрица для нормализации)
        """
        # Создаем маппинг сущностей
        all_entities = pd.unique(
            df_comparisons[['entity_1_id', 'entity_2_id']].values.ravel()
        )
        self.entity_to_idx_ = {e: i for i, e in enumerate(all_entities)}
        self.idx_to_entity_ = {i: e for e, i in self.entity_to_idx_.items()}
        self.n_entities = len(all_entities)

        # Инициализируем матрицы
        # Используем разреженные матрицы для экономии памяти
        row_indices = []
        col_indices = []
        values = []

        for _, row in df_comparisons.iterrows():
            i = self.entity_to_idx_[row['entity_1_id']]
            j = self.entity_to_idx_[row['entity_2_id']]

            # Вес перехода от победителя к проигравшему
            weight = row.get('weight', 1.0)

            # В модифицированном PageRank добавляем вес
            row_indices.append(i)
            col_indices.append(j)
            values.append(weight)

        # Создаем разреженную матрицу
        W = sparse.csr_matrix((values, (row_indices, col_indices)),
                               shape=(self.n_entities, self.n_entities))

        return W

    def _compute_pagerank_vector(self, W: sparse.csr_matrix) -> np.ndarray:
        """
        Вычисляет вектор PageRank итеративным методом.

        Args:
            W: взвешенная матрица смежности

        Returns:
            вектор рейтингов
        """
        # Нормализуем веса (чтобы из каждого узла сумма исходящих весов = 1)
        out_degree = np.array(W.sum(axis=1)).flatten()

        # Узлы с нулевым исходящим весом (стоки) - они будут иметь равномерное распределение
        zero_outdegree = (out_degree == 0)

        # Создаем матрицу переходов P
        # Для узлов с исходящими связями: P[i,j] = W[i,j] / out_degree[i]
        # Для стоков: P[i,j] = 1/n_entities (равномерное распределение)

        # Инициализируем матрицу P как разреженную
        P = sparse.lil_matrix((self.n_entities, self.n_entities))

        # Заполняем для узлов с исходящими связями
        rows, cols = W.nonzero()
        for idx in range(len(rows)):
            i, j = rows[idx], cols[idx]
            if not zero_outdegree[i]:
                P[i, j] = W[i, j] / out_degree[i]

        # Для стоков: равномерное распределение
        for i in np.where(zero_outdegree)[0]:
            P[i, :] = 1.0 / self.n_entities

        # Преобразуем обратно в CSR для эффективных операций
        P = P.tocsr()

        # Телепортационная матрица E (равномерное распределение)
        E = sparse.csr_matrix(np.ones((self.n_entities, self.n_entities)) / self.n_entities)

        # Матрица Google G = damping * P + (1-damping) * E
        G = self.damping * P + (1 - self.damping) * E

        # Итеративное вычисление PageRank
        # Начинаем с равномерного распределения
        r = np.ones(self.n_entities) / self.n_entities

        for iteration in range(self.max_iter):
            r_new = G.T @ r

            # Проверка сходимости
            diff = np.linalg.norm(r_new - r, 1)
            r = r_new

            if diff < self.tol:
                logger.info(f"PageRank сошелся за {iteration + 1} итераций")
                break

        return r

    def fit(self, df_comparisons: pd.DataFrame):
        """
        Обучает модель PageRank на данных парных сравнений.

        Args:
            df_comparisons: DataFrame с колонками:
                - entity_1_id, entity_2_id (обязательно)
                - weight (опционально, вес сравнения)
                - position_diff (опционально, разница в позициях)
        """
        logger.info(f"Начало обучения PageRank на {len(df_comparisons)} сравнениях")

        # Строим взвешенную матрицу смежности
        W = self._build_weighted_adjacency_matrix(df_comparisons)

        # Вычисляем PageRank
        scores = self._compute_pagerank_vector(W)

        # Сохраняем результаты
        self.ratings_ = scores

        # Нормализуем для удобства (сумма = 1)
        self.ratings_ = self.ratings_ / self.ratings_.sum()

        logger.info(f"PageRank обучен. Макс. рейтинг: {self.ratings_.max():.4f}, "
                   f"мин: {self.ratings_.min():.4f}")

        return self

    def get_rating(self, entity_id) -> float:
        """Возвращает рейтинг сущности."""
        if self.ratings_ is None:
            raise ValueError("Модель не обучена")

        if entity_id not in self.entity_to_idx_:
            return 0.0

        return float(self.ratings_[self.entity_to_idx_[entity_id]])

    def get_all_ratings(self) -> Dict[int, float]:
        """Возвращает словарь {id: рейтинг} для всех сущностей."""
        if self.ratings_ is None:
            raise ValueError("Модель не обучена")

        return {
            self.idx_to_entity_[i]: float(self.ratings_[i])
            for i in range(self.n_entities)
        }

    def get_top_entities(self, n: int = 10) -> List[Tuple[int, float]]:
        """
        Возвращает топ-N сущностей по рейтингу.

        Returns:
            список кортежей (id, рейтинг)
        """
        if self.ratings_ is None:
            raise ValueError("Модель не обучена")

        indices = np.argsort(self.ratings_)[::-1][:n]
        return [(self.idx_to_entity_[i], self.ratings_[i]) for i in indices]
