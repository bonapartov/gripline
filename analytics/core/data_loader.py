# -*- coding: utf-8 -*-
"""
Загрузчик данных из базы данных для аналитических моделей.
Преобразует сырые данные из Django ORM в форматы, пригодные для моделей.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class DataLoader:
    """
    Класс для загрузки и предварительной обработки данных из БД.
    """

    def __init__(self):
        """Инициализация загрузчика."""
        self.df_races = None
        self.df_chassis = None
        self.df_drivers = None
        self.df_tracks = None
        self.df_tyres = None

    def load_all_data(self):
        """
        Загружает все необходимые данные из базы.
        Вызывается один раз при инициализации.
        """
        from website.models import (
            RaceResult, Chassis, Driver, Track, Tyre,
        )

        logger.info("Начинаем загрузку данных из БД...")

        # Загружаем все результаты с предзагрузкой связанных объектов
        results = RaceResult.objects.select_related(
            'driver',
            'chassis_new',
            'team',
            'group',
            'group__page',
            'group__page__track',
            'group__race_class',
            'group__tyre',
            'group__tyre__brand',
            'group__tyre__type',
            'group__engine'
        ).all().order_by('group__page__first_published_at')

        # Преобразуем в pandas DataFrame
        data = []
        for r in results:
            # Пропускаем записи без шасси или пилота
            if not r.chassis_new or not r.driver:
                continue

            # Получаем дату окончания этапа
            occurrences = r.group.page.occurrences.all()
            if occurrences:
                race_date = occurrences.first().end or r.group.page.first_published_at
            else:
                race_date = r.group.page.first_published_at

            # Формируем строку данных
            row = {
                'group_id': r.group.id,  # добавляем ID группы результатов
                'race_id': r.id,
                'date': race_date,
                'year': race_date.year,
                'month': race_date.month,

                # Сущности
                'chassis_id': r.chassis_new.id,
                'chassis_name': r.chassis_new.name,
                'driver_id': r.driver.id,
                'driver_name': r.driver.full_name,
                'team_id': r.team.id if r.team else None,

                # Контекст
                'track_id': r.group.page.track.id if r.group.page.track else None,
                'track_name': r.group.page.track.name if r.group.page.track else None,
                'class_id': r.group.race_class.id,
                'class_name': r.group.race_class.name,
                'tyre_id': r.group.tyre.id if r.group.tyre else None,
                'tyre_name': str(r.group.tyre) if r.group.tyre else None,
                'engine_id': r.group.engine.id if r.group.engine else None,
                'engine_name': r.group.engine.name if r.group.engine else None,

                # Погода
                'temperature': r.group.air_temperature,
                'humidity': r.group.humidity,
                'pressure': r.group.pressure,
                'wind_speed': r.group.wind_speed,
                'uv_index': r.group.uv_index,
                'precipitation': getattr(r.group, 'precipitation', None),

                # Результат
                'position': r.position,
                'points': r.points,
            }
            data.append(row)

        self.df_races = pd.DataFrame(data)
        logger.info(f"Загружено {len(self.df_races)} записей о гонках")

        # Загружаем справочники
        self.df_chassis = pd.DataFrame(list(Chassis.objects.all().values('id', 'name', 'country')))
        self.df_drivers = pd.DataFrame(list(Driver.objects.all().values('id', 'first_name', 'last_name')))
        self.df_tracks = pd.DataFrame(list(Track.objects.all().values('id', 'name', 'city')))
        self.df_tyres = pd.DataFrame(list(Tyre.objects.all().values('id', 'brand__name', 'type__name')))

        logger.info("Загрузка данных завершена")
        return self.df_races

    def create_pairwise_comparisons(self, entity_type='chassis'):
        """
        Создает матрицу парных сравнений для указанной сущности.

        Args:
            entity_type: 'chassis' или 'driver'

        Returns:
            DataFrame с колонками: entity_1_id, entity_2_id, winner_id, weight
        """
        if self.df_races is None:
            self.load_all_data()

        comparisons = []

        # Группируем по group_id (один заезд)
        for group_id, group in self.df_races.groupby('group_id'):
            if len(group) < 2:
                continue

            # Сортируем по месту
            group = group.sort_values('position')

            # Создаем все попарные сравнения
            for i, row_i in group.iterrows():
                for j, row_j in group.iterrows():
                    if i == j:
                        continue

                    # Определяем победителя (меньшее место = победа)
                    if row_i['position'] < row_j['position']:
                        winner_id = row_i[f'{entity_type}_id']
                        loser_id = row_j[f'{entity_type}_id']
                    else:
                        winner_id = row_j[f'{entity_type}_id']
                        loser_id = row_i[f'{entity_type}_id']

                    # Вес сравнения (чем больше разница в местах, тем меньше вес)
                    position_diff = abs(row_i['position'] - row_j['position'])
                    weight = 1.0 / (1.0 + position_diff)

                    comparisons.append({
                        'entity_1_id': winner_id,
                        'entity_2_id': loser_id,
                        'winner_id': winner_id,
                        'loser_id': loser_id,
                        'weight': weight,
                        'group_id': group_id,
                        'race_id': group['race_id'].iloc[0] if 'race_id' in group.columns else None,
                        'temperature': group['temperature'].iloc[0] if 'temperature' in group.columns else None,
                        'tyre_id': group['tyre_id'].iloc[0] if 'tyre_id' in group.columns else None,
                        'track_id': group['track_id'].iloc[0] if 'track_id' in group.columns else None,
                    })

        df = pd.DataFrame(comparisons)
        logger.info(f"Создано {len(df)} парных сравнений для {entity_type}")
        return df

    def get_temperature_bins(self, df, bins=5):
        """
        Разбивает температуру на бины для категориального анализа.
        """
        if 'temperature' not in df.columns:
            return df

        df['temp_bin'] = pd.cut(
            df['temperature'],
            bins=bins,
            labels=[f'{int(b)}°C' for b in np.linspace(-10, 40, bins)]
        )
        return df

    def create_contextual_comparisons(self, entity_type='driver'):
        """
        Создает матрицу парных сравнений с контекстными признаками.

        Args:
            entity_type: 'driver' или 'chassis'

        Returns:
            DataFrame с колонками:
            entity_1_id, entity_2_id, winner_id, weight,
            temperature, precipitation, tyre_id, track_id
        """
        if self.df_races is None:
            self.load_all_data()

        comparisons = []

        # Группируем по group_id (один заезд)
        for group_id, group in self.df_races.groupby('group_id'):
            if len(group) < 2:
                continue

            group = group.sort_values('position')

            # Получаем контекст для всего заезда (одинаков для всех)
            temperature = group['temperature'].iloc[0] if 'temperature' in group.columns else None
            precipitation = group['precipitation'].iloc[0] if 'precipitation' in group.columns else None
            tyre_id = group['tyre_id'].iloc[0] if 'tyre_id' in group.columns else None
            track_id = group['track_id'].iloc[0] if 'track_id' in group.columns else None

            # Создаем все попарные сравнения
            for i, row_i in group.iterrows():
                for j, row_j in group.iterrows():
                    if i == j:
                        continue

                    # Определяем победителя
                    if row_i['position'] < row_j['position']:
                        winner_id = row_i[f'{entity_type}_id']
                        loser_id = row_j[f'{entity_type}_id']
                    else:
                        winner_id = row_j[f'{entity_type}_id']
                        loser_id = row_i[f'{entity_type}_id']

                    # Вес сравнения
                    position_diff = abs(row_i['position'] - row_j['position'])
                    weight = 1.0 / (1.0 + position_diff)

                    comparisons.append({
                        'entity_1_id': winner_id,
                        'entity_2_id': loser_id,
                        'winner_id': winner_id,
                        'loser_id': loser_id,
                        'weight': weight,
                        'group_id': group_id,
                        'temperature': temperature,
                        'precipitation': precipitation,
                        'tyre_id': tyre_id,
                        'track_id': track_id,
                    })

        df = pd.DataFrame(comparisons)
        logger.info(f"Создано {len(df)} контекстных сравнений для {entity_type}")
        return df
