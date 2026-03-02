# -*- coding: utf-8 -*-
"""
Тесты для аналитических моделей.
"""

import unittest
import pandas as pd
import numpy as np
from analytics.bradley_terry.model import BradleyTerryLasso


class TestBradleyTerry(unittest.TestCase):
    """Тесты модели Брэдли-Терри."""

    def setUp(self):
        """Подготовка тестовых данных."""
        # Простой случай: 3 сущности с транзитивными предпочтениями
        self.test_data = pd.DataFrame({
            'entity_1_id': [1, 1, 2],
            'entity_2_id': [2, 3, 3],
            'winner_id': [1, 1, 2],
            'weight': [1.0, 1.0, 1.0]
        })

    def test_model_fit(self):
        """Проверка, что модель обучается."""
        model = BradleyTerryLasso(alpha=0.1)
        model.fit(self.test_data)

        self.assertIsNotNone(model.ratings_)
        self.assertEqual(len(model.ratings_), 3)

    def test_predict_proba(self):
        """Проверка предсказаний."""
        model = BradleyTerryLasso(alpha=0.1)
        model.fit(self.test_data)

        # Сущность 1 должна иметь больший рейтинг, чем 2 и 3
        prob_1_vs_2 = model.predict_proba(1, 2)
        prob_1_vs_3 = model.predict_proba(1, 3)

        self.assertGreater(prob_1_vs_2, 0.5)
        self.assertGreater(prob_1_vs_3, 0.5)

    def test_get_rating(self):
        """Проверка получения рейтинга."""
        model = BradleyTerryLasso(alpha=0.1)
        model.fit(self.test_data)

        rating_1 = model.get_rating(1)
        rating_2 = model.get_rating(2)
        rating_3 = model.get_rating(3)

        # Рейтинги должны быть упорядочены: 1 > 2 > 3
        self.assertGreater(rating_1, rating_2)
        self.assertGreater(rating_2, rating_3)


if __name__ == '__main__':
    unittest.main()
