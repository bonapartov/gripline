# -*- coding: utf-8 -*-
"""
Модуль предобработки данных для аналитических моделей.
Нормализация, кодирование категорий, создание признаков.
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler, LabelEncoder
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class DataPreprocessor:
    """
    Класс для предобработки данных перед подачей в модели.
    """

    def __init__(self):
        self.scaler = StandardScaler()
        self.label_encoders = {}
        self.fitted = False

    def fit_transform(self, df_races: pd.DataFrame) -> pd.DataFrame:
        """
        Обучает предобработчик и преобразует данные.

        Args:
            df_races: сырой DataFrame с гонками

        Returns:
            DataFrame с закодированными и нормализованными признаками
        """
        df = df_races.copy()

        # Кодируем категориальные переменные
        categorical_cols = ['track_id', 'class_id', 'tyre_id', 'engine_id']
        for col in categorical_cols:
            if col in df.columns:
                self.label_encoders[col] = LabelEncoder()
                df[f'{col}_encoded'] = self.label_encoders[col].fit_transform(
                    df[col].fillna(-1).astype(int)
                )

        # Создаем признаки из даты
        if 'date' in df.columns:
            df['day_of_year'] = df['date'].dt.dayofyear
            df['week_of_year'] = df['date'].dt.isocalendar().week.astype(int)
            df['season'] = df['month'].apply(self._get_season)

        # Нормализуем числовые признаки
        numeric_cols = ['temperature', 'humidity', 'pressure', 'wind_speed']
        available_numeric = [c for c in numeric_cols if c in df.columns]

        if available_numeric:
            df[available_numeric] = self.scaler.fit_transform(
                df[available_numeric].fillna(df[available_numeric].mean())
            )

        # Добавляем квадратичные признаки для температуры
        if 'temperature' in df.columns:
            df['temp_squared'] = df['temperature'] ** 2

        self.fitted = True
        logger.info(f"Предобработка завершена. Формат данных: {df.shape}")
        return df

    def transform(self, df_races: pd.DataFrame) -> pd.DataFrame:
        """
        Применяет обученное преобразование к новым данным.
        """
        if not self.fitted:
            raise ValueError("Preprocessor must be fitted first")

        df = df_races.copy()

        for col, encoder in self.label_encoders.items():
            if col in df.columns:
                # Обрабатываем новые значения, которых не было при обучении
                unknown_mask = ~df[col].fillna(-1).astype(int).isin(encoder.classes_)
                df.loc[unknown_mask, col] = -1
                df[f'{col}_encoded'] = encoder.transform(df[col].fillna(-1).astype(int))

        if 'date' in df.columns:
            df['day_of_year'] = df['date'].dt.dayofyear
            df['week_of_year'] = df['date'].dt.isocalendar().week.astype(int)
            df['season'] = df['month'].apply(self._get_season)

        numeric_cols = ['temperature', 'humidity', 'pressure', 'wind_speed']
        available_numeric = [c for c in numeric_cols if c in df.columns]

        if available_numeric:
            df[available_numeric] = self.scaler.transform(
                df[available_numeric].fillna(df[available_numeric].mean())
            )

        if 'temperature' in df.columns:
            df['temp_squared'] = df['temperature'] ** 2

        return df

    def _get_season(self, month):
        """Определяет сезон по месяцу."""
        if month in [12, 1, 2]:
            return 'winter'
        elif month in [3, 4, 5]:
            return 'spring'
        elif month in [6, 7, 8]:
            return 'summer'
        else:
            return 'autumn'


def create_entity_mapping(df: pd.DataFrame, entity_col: str) -> Dict:
    """
    Создает словарь для маппинга ID сущностей в индексы.

    Args:
        df: DataFrame с данными
        entity_col: название колонки с ID сущности

    Returns:
        Словарь {entity_id: index}
    """
    unique_ids = df[entity_col].unique()
    return {id_: idx for idx, id_ in enumerate(unique_ids)}
