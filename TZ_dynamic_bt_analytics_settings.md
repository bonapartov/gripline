# ТЗ: Dynamic Bradley-Terry + AnalyticsSettings

## Цель

Добавить экспоненциальный временной вес к парным сравнениям в Bradley-Terry модели
(Dynamic BT), чтобы рейтинг неактивных пилотов естественно снижался без фиктивных
результатов. Вынести все ключевые параметры модели в singleton-модель `AnalyticsSettings`
с UI в Wagtail admin. CLI-аргументы сохранить как override над значениями из БД.

---

## Формула temporal decay

```
days = (today - race_date).days
is_inactive = days > settings.inactive_threshold_days
λ = settings.lambda_inactive if is_inactive else settings.lambda_active
temporal_weight = exp(-λ × days / 365)
final_weight = position_weight × temporal_weight
```

**Дефолтные значения:**
- `lambda_active = 0.8` → победа 1.5 года назад весит ~50% от свежей
- `lambda_inactive = 2.0` → победа 1.5 года назад весит ~5%
- `inactive_threshold_days = 180` → порог неактивности: 6 месяцев без гонок в классе

**Приоритет параметров:** CLI-аргумент > значение из БД (`AnalyticsSettings`) > hardcoded default

---

## Часть 1: Модель AnalyticsSettings

### 1.1 `website/models.py` — добавить после класса `AnalyticsMetadata` (~line 1310)

```python
class AnalyticsSettings(models.Model):
    """
    Singleton-модель глобальных параметров аналитического движка.
    Доступна через AnalyticsSettings.get().
    Изменения вступают в силу при следующем запуске update_ratings.
    """

    # --- Temporal decay ---
    lambda_active = models.FloatField(
        default=0.8,
        verbose_name="λ активного пилота",
        help_text="Скорость затухания для пилотов с недавними гонками. "
                  "Полураспад = ln(2)/λ лет. Рекомендуется 0.5–1.2.",
    )
    lambda_inactive = models.FloatField(
        default=2.0,
        verbose_name="λ неактивного пилота",
        help_text="Скорость затухания для пилотов без гонок дольше порога. "
                  "Должен быть выше lambda_active. Рекомендуется 1.5–3.0.",
    )
    inactive_threshold_days = models.IntegerField(
        default=180,
        verbose_name="Порог неактивности (дней)",
        help_text="Количество дней без гонок в классе после которого "
                  "применяется lambda_inactive. Один летний сезон ≈ 180 дней.",
    )

    # --- Пороги данных ---
    min_races_per_class = models.IntegerField(
        default=5,
        verbose_name="Мин. гонок для расчёта класса",
        help_text="Класс с меньшим количеством гонок пропускается при расчёте BT.",
    )
    min_comparisons = models.IntegerField(
        default=10,
        verbose_name="Мин. парных сравнений (BT)",
        help_text="Класс с меньшим количеством парных сравнений пропускается.",
    )
    min_starts_display = models.IntegerField(
        default=3,
        verbose_name="Мин. стартов для отображения рейтинга",
        help_text="Пилоты с меньшим числом стартов получают пометку ⚠️.",
    )
    min_races_context = models.IntegerField(
        default=10,
        verbose_name="Мин. гонок для контекстной модели",
    )
    min_comparisons_context = models.IntegerField(
        default=20,
        verbose_name="Мин. парных сравнений (контекстная модель)",
    )

    # --- Параметры моделей ---
    bt_alpha = models.FloatField(
        default=0.1,
        verbose_name="Alpha (L1-регуляризация BT)",
        help_text="Lasso-регуляризация Bradley-Terry. Выше → сильнее сглаживание "
                  "к среднему для пилотов с малым числом гонок. Диапазон: 0.01–1.0.",
    )
    pagerank_damping = models.FloatField(
        default=0.85,
        verbose_name="Damping factor (PageRank)",
        help_text="Коэффициент затухания PageRank. Стандартное значение 0.85. "
                  "Диапазон: 0.5–0.99.",
    )
    ensemble_min_common_drivers = models.IntegerField(
        default=3,
        verbose_name="Мин. общих пилотов для ансамбля",
        help_text="Минимальное число общих пилотов между классами для "
                  "объединения в ансамбль.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки аналитики"
        verbose_name_plural = "Настройки аналитики"

    def __str__(self):
        return f"AnalyticsSettings (λ={self.lambda_active}/{self.lambda_inactive}, " \
               f"inactive={self.inactive_threshold_days}d)"

    @classmethod
    def get(cls):
        """Получить единственный экземпляр настроек (создаёт если не существует)."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
```

### 1.2 Миграция

```bash
python manage.py makemigrations website --name analytics_settings
python manage.py migrate
```

---

## Часть 2: Регистрация в Wagtail admin

### `website/wagtail_hooks.py` — добавить по образцу `OrganizerSettingsAdmin`

```python
from wagtail.contrib.modeladmin.options import ModelAdmin, modeladmin_register
from .models import AnalyticsSettings


class AnalyticsSettingsAdmin(ModelAdmin):
    model = AnalyticsSettings
    menu_label = "Параметры рейтинга"
    menu_icon = "cog"
    menu_order = 900
    add_to_settings_menu = True       # появится в разделе Settings Wagtail
    list_display = [
        "lambda_active",
        "lambda_inactive",
        "inactive_threshold_days",
        "bt_alpha",
        "updated_at",
    ]

modeladmin_register(AnalyticsSettingsAdmin)
```

> Если в проекте есть `ModelAdminGroup` — добавить `AnalyticsSettingsAdmin`
> в его `items` вместо отдельной регистрации.

---

## Часть 3: Temporal decay в коде расчёта

### 3.1 `website/management/commands/update_ratings.py`

#### `handle()` (~line 30) — приоритет CLI > БД

```python
from website.models import AnalyticsSettings

def handle(self, *args, **options):
    settings = AnalyticsSettings.get()

    # CLI override: если аргумент передан явно — перебивает значение из БД
    if options.get('alpha') is not None:
        settings.bt_alpha = options['alpha']
    if options.get('damping') is not None:
        settings.pagerank_damping = options['damping']
    if options.get('min_starts') is not None:
        settings.min_starts_display = options['min_starts']
    if options.get('lambda_active') is not None:
        settings.lambda_active = options['lambda_active']
    if options.get('lambda_inactive') is not None:
        settings.lambda_inactive = options['lambda_inactive']
    if options.get('inactive_threshold_days') is not None:
        settings.inactive_threshold_days = options['inactive_threshold_days']

    # Далее передавать settings во все _update_* методы
    ...
```

#### Добавить CLI-аргументы в `add_arguments()`

```python
def add_arguments(self, parser):
    # существующие аргументы сохранить
    parser.add_argument('--alpha', type=float, default=None,
                        help='Override bt_alpha из AnalyticsSettings')
    parser.add_argument('--damping', type=float, default=None,
                        help='Override pagerank_damping из AnalyticsSettings')
    parser.add_argument('--min-starts', type=int, default=None,
                        help='Override min_starts_display из AnalyticsSettings')
    parser.add_argument('--lambda-active', type=float, default=None,
                        help='Override lambda_active из AnalyticsSettings')
    parser.add_argument('--lambda-inactive', type=float, default=None,
                        help='Override lambda_inactive из AnalyticsSettings')
    parser.add_argument('--inactive-threshold-days', type=int, default=None,
                        help='Override inactive_threshold_days из AnalyticsSettings')
```

#### `_create_class_comparisons()` (~line 390) — добавить temporal decay

```python
def _create_class_comparisons(self, df_class, entity_type, settings):
    import math
    from datetime import date

    today = date.today()
    comparisons = []

    for group_id, group in df_class.groupby('group_id'):
        if len(group) < 2:
            continue
        group = group.sort_values('position')

        # Temporal weight
        race_date = group['date'].iloc[0]
        if race_date is not None:
            if hasattr(race_date, 'date'):
                race_date = race_date.date()
            days = (today - race_date).days
            is_inactive = days > settings.inactive_threshold_days
            lam = settings.lambda_inactive if is_inactive else settings.lambda_active
            temporal_weight = math.exp(-lam * days / 365)
        else:
            temporal_weight = 1.0  # нет даты — нейтральный вес

        for i, row_i in group.iterrows():
            for j, row_j in group.iterrows():
                if i >= j:
                    continue
                # ... существующая логика формирования пары ...
                position_diff = abs(row_i['position'] - row_j['position'])
                weight = (1.0 / (1.0 + position_diff)) * temporal_weight
                comparisons.append({
                    # ... существующие поля ...
                    'weight': weight,
                    'race_date': race_date,   # для отладки
                    'temporal_weight': round(temporal_weight, 4),  # для отладки
                })

    return pd.DataFrame(comparisons)
```

#### `_update_driver_bt_ratings()` (~line 145) — читать из settings

```python
def _update_driver_bt_ratings(self, settings):
    # Заменить захардкоженные константы:
    # было:  if race_count < 5:
    # стало: if race_count < settings.min_races_per_class:

    # было:  if len(comparisons) < 10:
    # стало: if len(comparisons) < settings.min_comparisons:

    # было:  alpha=0.1
    # стало: alpha=settings.bt_alpha

    # было:  min_starts=3
    # стало: min_starts=settings.min_starts_display

    # Передавать settings в _create_class_comparisons:
    comparisons = self._create_class_comparisons(df_class, entity_type, settings)
```

#### `_update_chassis_bt_ratings()` (~line 342)

```python
def _update_chassis_bt_ratings(self, settings):
    comparisons = loader.create_pairwise_comparisons(settings=settings)
    # alpha=settings.bt_alpha
```

#### `_update_context_ratings()` (~line 200)

```python
def _update_context_ratings(self, settings):
    comparisons = loader.create_contextual_comparisons(settings=settings)
    # min_races=settings.min_races_context
    # min_comparisons=settings.min_comparisons_context
```

---

### 3.2 `analytics/core/data_loader.py`

#### `create_pairwise_comparisons()` (~line 120)

```python
def create_pairwise_comparisons(self, settings=None):
    import math
    from datetime import date

    today = date.today()

    for group_id, group in df.groupby('group_id'):
        race_date = group['date'].iloc[0]

        if settings is not None and race_date is not None:
            if hasattr(race_date, 'date'):
                race_date = race_date.date()
            days = (today - race_date).days
            is_inactive = days > settings.inactive_threshold_days
            lam = settings.lambda_inactive if is_inactive else settings.lambda_active
            temporal_weight = math.exp(-lam * days / 365)
        else:
            temporal_weight = 1.0  # settings=None → обратная совместимость

        # weight = position_weight * temporal_weight
```

#### `create_contextual_comparisons()` (~line 192)

Аналогично `create_pairwise_comparisons` — добавить параметр `settings=None`
и ту же логику temporal_weight.

---

### 3.3 `analytics/bradley_terry/model.py` — **не трогать**

`_prepare_data()` уже читает `weight` из DataFrame через `row.get('weight', 1.0)`
и передаёт в `sample_weight` sklearn. Изменений не требует.

---

## Файлы для изменения — итого

| Файл | Что меняем |
|------|-----------|
| `website/models.py` | Добавить `AnalyticsSettings` после `AnalyticsMetadata` |
| `website/wagtail_hooks.py` | Добавить `AnalyticsSettingsAdmin` |
| `website/migrations/` | Новая миграция `analytics_settings` |
| `website/management/commands/update_ratings.py` | `handle`, `add_arguments`, `_update_driver_bt_ratings`, `_update_chassis_bt_ratings`, `_update_context_ratings`, `_create_class_comparisons` |
| `analytics/core/data_loader.py` | `create_pairwise_comparisons`, `create_contextual_comparisons` |

**Не трогаем:**
- `analytics/bradley_terry/model.py`
- `analytics/pagerank/model.py`
- `analytics/ensemble/`

---

## Проверка

```bash
# 1. Миграция
python manage.py makemigrations website --name analytics_settings
python manage.py migrate

# 2. Базовый запуск (параметры из БД, дефолты)
python manage.py update_ratings --entity driver --model bt

# 3. Проверка обратной совместимости — λ=0 должен дать прежние рейтинги
python manage.py update_ratings --entity driver --model bt \
    --lambda-active 0.0 --lambda-inactive 0.0

# 4. Проверка decay — неактивные пилоты должны получить рейтинг ниже
python manage.py update_ratings --entity driver --model bt \
    --lambda-active 0.8 --lambda-inactive 2.0

# 5. CLI override — временный тест с другим alpha
python manage.py update_ratings --entity driver --model bt --alpha 0.05

# 6. Через Wagtail admin:
#    Settings → Параметры рейтинга → изменить lambda_active → сохранить
#    python manage.py update_ratings --entity driver --model bt
#    Убедиться что новое значение применилось
```

---

## Ожидаемый эффект

- Пилот ушедший в другой класс 6+ месяцев назад → его исторические победы
  начинают весить в 2.5× меньше при каждом пересчёте
- Через 1–1.5 сезона без гонок → рейтинг опускается ниже активных пилотов
  со средними результатами
- Активные пилоты с гонками последних 6 месяцев — практически без изменений
- Все параметры меняются через Wagtail admin без деплоя
- CLI override позволяет быстро тестировать параметры не меняя БД
