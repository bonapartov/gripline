import requests
import datetime
import logging

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

def fetch_weather_data(latitude, longitude, target_date, target_time):
    if target_date is None:
            print("Ошибка: target_date is None")
            return None
    """
    Запрашивает исторические данные о погоде у Open-Meteo

    Args:
        latitude (float): Широта
        longitude (float): Долгота
        target_date (date): Дата заезда
        target_time (time): Время заезда

    Returns:
        dict: Словарь с погодными данными или None в случае ошибки
    """

    # Формируем дату в формате YYYY-MM-DD
    date_str = target_date.strftime("%Y-%m-%d")

    # URL для Historical Weather API
    url = "https://archive-api.open-meteo.com/v1/archive"

    # Параметры запроса
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": date_str,
        "end_date": date_str,
        "hourly": [
            "temperature_2m",
            "relative_humidity_2m",
            "pressure_msl",
            "wind_speed_10m",
            "shortwave_radiation",
            "precipitation"
        ],
        "timezone": "Europe/Moscow"  # Можно сделать настраиваемым позже
    }

    try:
        # Выполняем запрос
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()  # Проверяем на ошибки HTTP

        data = response.json()

        # Ищем индекс нужного часа
        target_hour = target_time.hour
        hourly_times = data.get("hourly", {}).get("time", [])

        # Находим позицию нужного часа
        hour_index = None
        for i, time_str in enumerate(hourly_times):
            if f"T{target_hour:02d}:00" in time_str:
                hour_index = i
                break

        if hour_index is None:
            logger.warning(f"Час {target_hour}:00 не найден в данных API")
            return None

        # Собираем данные
        hourly_data = data.get("hourly", {})

        # Давление в гПа переводим в мм рт. ст. (1 гПа ≈ 0.75 мм рт. ст.)
        pressure_hpa = hourly_data.get("pressure_msl", [None])[hour_index]
        pressure_mm = round(pressure_hpa * 0.75) if pressure_hpa else None

        # УФ-индекс примерно оцениваем по солнечной радиации (грубое приближение)
        radiation = hourly_data.get("shortwave_radiation", [None])[hour_index]
        uv_estimate = round(radiation / 50, 1) if radiation else None

        weather_data = {
            "air_temperature": hourly_data.get("temperature_2m", [None])[hour_index],
            "humidity": hourly_data.get("relative_humidity_2m", [None])[hour_index],
            "pressure": pressure_mm,
            "wind_speed": hourly_data.get("wind_speed_10m", [None])[hour_index],
            "uv_index": uv_estimate,
            "precipitation": hourly_data.get("precipitation", [None])[hour_index],
        }

        logger.info(f"Погода успешно получена: {weather_data}")
        return weather_data

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к Open-Meteo: {e}")
        return None
    except (KeyError, IndexError, ValueError) as e:
        logger.error(f"Ошибка при обработке данных от Open-Meteo: {e}")
        return None


# ============================================================
# Виджет погоды для этапа (StagePage): прогноз / статистическая
# оценка по прошлым годам / архив фактической погоды.
# ============================================================

ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"

FORECAST_HORIZON_DAYS = 15  # за пределами — статистическая оценка (climatology)
CLIMATOLOGY_YEARS = 5       # сколько прошлых лет усредняем для оценки
DAY_START_HOUR = 9
DAY_END_HOUR = 18

# WMO weathercode (Open-Meteo) → человекочитаемое описание + иконка Font Awesome 6 Solid
WMO_CODE_MAP = {
    0: {"description": "Ясно", "icon": "fa-sun"},
    1: {"description": "Малооблачно", "icon": "fa-cloud-sun"},
    2: {"description": "Переменная облачность", "icon": "fa-cloud-sun"},
    3: {"description": "Пасмурно", "icon": "fa-cloud"},
    45: {"description": "Туман", "icon": "fa-smog"},
    48: {"description": "Изморозь", "icon": "fa-smog"},
    51: {"description": "Морось", "icon": "fa-cloud-rain"},
    53: {"description": "Морось", "icon": "fa-cloud-rain"},
    55: {"description": "Морось", "icon": "fa-cloud-rain"},
    56: {"description": "Ледяная морось", "icon": "fa-cloud-rain"},
    57: {"description": "Ледяная морось", "icon": "fa-cloud-rain"},
    61: {"description": "Дождь", "icon": "fa-cloud-rain"},
    63: {"description": "Дождь", "icon": "fa-cloud-rain"},
    65: {"description": "Сильный дождь", "icon": "fa-cloud-showers-heavy"},
    66: {"description": "Ледяной дождь", "icon": "fa-cloud-rain"},
    67: {"description": "Сильный ледяной дождь", "icon": "fa-cloud-showers-heavy"},
    71: {"description": "Снег", "icon": "fa-snowflake"},
    73: {"description": "Снег", "icon": "fa-snowflake"},
    75: {"description": "Сильный снегопад", "icon": "fa-snowflake"},
    77: {"description": "Снежная крупа", "icon": "fa-snowflake"},
    80: {"description": "Ливень", "icon": "fa-cloud-showers-heavy"},
    81: {"description": "Ливень", "icon": "fa-cloud-showers-heavy"},
    82: {"description": "Сильный ливень", "icon": "fa-cloud-showers-heavy"},
    85: {"description": "Снегопад", "icon": "fa-snowflake"},
    86: {"description": "Сильный снегопад", "icon": "fa-snowflake"},
    95: {"description": "Гроза", "icon": "fa-bolt"},
    96: {"description": "Гроза с градом", "icon": "fa-cloud-bolt"},
    99: {"description": "Сильная гроза с градом", "icon": "fa-cloud-bolt"},
}
DEFAULT_WEATHER_CODE = {"description": "Переменная облачность", "icon": "fa-cloud"}


def _describe_code(code):
    return WMO_CODE_MAP.get(code, DEFAULT_WEATHER_CODE)


def _dominant_code(codes):
    """Мода списка weathercode; при равенстве — самый ранний встреченный код."""
    codes = [c for c in codes if c is not None]
    if not codes:
        return None
    counts = {}
    order = []
    for c in codes:
        if c not in counts:
            counts[c] = 0
            order.append(c)
        counts[c] += 1
    return max(order, key=lambda c: counts[c])


def _fetch_hourly_range(base_url, latitude, longitude, target_date,
                         start_hour=DAY_START_HOUR, end_hour=DAY_END_HOUR):
    """
    Один запрос к Open-Meteo (forecast или archive — определяется base_url)
    за один календарный день. Возвращает почасовые массивы в диапазоне
    [start_hour, end_hour], либо None при ошибке/отсутствии данных.
    """
    date_str = target_date.strftime("%Y-%m-%d")
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": date_str,
        "end_date": date_str,
        "hourly": [
            "temperature_2m",
            "relative_humidity_2m",
            "wind_speed_10m",
            "precipitation",
            "weathercode",
        ],
        "wind_speed_unit": "ms",  # совпадает с маркировкой "м/с" на RaceClassResultGroup
        "timezone": "Europe/Moscow",
    }

    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])

        indices = [
            i for i, time_str in enumerate(times)
            if time_str.startswith(date_str) and start_hour <= int(time_str[11:13]) <= end_hour
        ]
        if not indices:
            logger.warning(f"Нет часовых данных за {date_str} в диапазоне {start_hour}-{end_hour} ({base_url})")
            return None

        return {
            "times": [times[i] for i in indices],
            "temperature": [hourly.get("temperature_2m", [])[i] for i in indices],
            "humidity": [hourly.get("relative_humidity_2m", [])[i] for i in indices],
            "wind_speed": [hourly.get("wind_speed_10m", [])[i] for i in indices],
            "precipitation": [hourly.get("precipitation", [])[i] for i in indices],
            "weathercode": [hourly.get("weathercode", [])[i] for i in indices],
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к Open-Meteo ({base_url}): {e}")
        return None
    except (KeyError, IndexError, ValueError) as e:
        logger.error(f"Ошибка при обработке данных от Open-Meteo ({base_url}): {e}")
        return None


def _build_widget_data(hourly_slice, category, badge_label, disclaimer=None):
    """Строит нормализованный dict для weather_widget.html из часового среза."""
    if not hourly_slice:
        return None

    temps = [t for t in hourly_slice["temperature"] if t is not None]
    if not temps:
        return None

    dominant = _dominant_code(hourly_slice["weathercode"])
    info = _describe_code(dominant)

    humidity_values = [h for h in hourly_slice["humidity"] if h is not None]
    wind_values = [w for w in hourly_slice["wind_speed"] if w is not None]
    precip_values = [p for p in hourly_slice["precipitation"] if p is not None]

    hourly_out = []
    for i, time_str in enumerate(hourly_slice["times"]):
        temp = hourly_slice["temperature"][i]
        if temp is None:
            continue
        hour = int(time_str[11:13])
        if hour % 3 != 0:
            continue
        hourly_out.append({
            "time": f"{hour:02d}:00",
            "temp": round(temp),
            "precipitation": round(hourly_slice["precipitation"][i] or 0, 1),
            "icon": _describe_code(hourly_slice["weathercode"][i])["icon"],
        })

    return {
        "category": category,
        "badge_label": badge_label,
        "temp_min": round(min(temps)),
        "temp_max": round(max(temps)),
        "description": info["description"],
        "icon": info["icon"],
        "precipitation_total": round(sum(precip_values), 1) if precip_values else 0,
        "wind_speed_avg": round(sum(wind_values) / len(wind_values), 1) if wind_values else None,
        "humidity_avg": round(sum(humidity_values) / len(humidity_values)) if humidity_values else None,
        "hourly": hourly_out,
        "disclaimer": disclaimer,
    }


def _merge_hourly_samples(samples):
    """Усредняет N часовых срезов (по одному на прошлый год) поэлементно по позиции в окне."""
    samples = [s for s in samples if s]
    if not samples:
        return None

    length = min(len(s["times"]) for s in samples)
    merged = {
        "times": samples[0]["times"][:length],
        "temperature": [], "humidity": [], "wind_speed": [], "precipitation": [], "weathercode": [],
    }

    for i in range(length):
        temps = [s["temperature"][i] for s in samples if s["temperature"][i] is not None]
        hums = [s["humidity"][i] for s in samples if s["humidity"][i] is not None]
        winds = [s["wind_speed"][i] for s in samples if s["wind_speed"][i] is not None]
        precs = [s["precipitation"][i] for s in samples if s["precipitation"][i] is not None]
        codes = [s["weathercode"][i] for s in samples if s["weathercode"][i] is not None]

        merged["temperature"].append(sum(temps) / len(temps) if temps else None)
        merged["humidity"].append(sum(hums) / len(hums) if hums else None)
        merged["wind_speed"].append(sum(winds) / len(winds) if winds else None)
        merged["precipitation"].append(sum(precs) / len(precs) if precs else None)
        merged["weathercode"].append(_dominant_code(codes))

    return merged


def fetch_forecast_weather(latitude, longitude, target_date):
    """Реальный прогноз погоды (в пределах горизонта Open-Meteo, обычно ~15 дней)."""
    hourly_slice = _fetch_hourly_range(FORECAST_API_URL, latitude, longitude, target_date)
    return _build_widget_data(hourly_slice, category="forecast", badge_label="ПРОГНОЗ")


def fetch_archive_day_weather(latitude, longitude, target_date):
    """Фактическая (архивная) погода за прошедшую дату."""
    hourly_slice = _fetch_hourly_range(ARCHIVE_API_URL, latitude, longitude, target_date)
    return _build_widget_data(hourly_slice, category="archive", badge_label="АРХИВ")


def fetch_climatology_estimate(latitude, longitude, target_date, years=CLIMATOLOGY_YEARS):
    """
    Статистическая оценка погоды для дат за пределами горизонта прогноза:
    усредняем архивные данные за тот же календарный день/месяц за последние N лет.
    """
    samples = []
    for i in range(1, years + 1):
        try:
            past_date = target_date.replace(year=target_date.year - i)
        except ValueError:
            # 29 февраля в невисокосном прошлом году
            past_date = target_date.replace(year=target_date.year - i, day=28)
        samples.append(_fetch_hourly_range(ARCHIVE_API_URL, latitude, longitude, past_date))

    merged = _merge_hourly_samples(samples)
    disclaimer = (
        "Приблизительная оценка по статистике прошлых лет — "
        "точный прогноз появится ближе к дате этапа."
    )
    return _build_widget_data(merged, category="estimate", badge_label="ПРИБЛИЗИТЕЛЬНО", disclaimer=disclaimer)


def get_stage_weather(stage):
    """
    Погода для этапа (StagePage) с кэшированием через Django cache framework.
    Категория определяется автоматически по stage.start_date:
        прошёл          → archive (кэш навсегда, дата не меняется)
        ≤15 дней вперёд  → forecast (кэш до конца дня — ключ содержит "сегодня")
        >15 дней вперёд  → estimate (статистика прошлых лет, кэш до конца дня)
    Возвращает None, если у этапа нет трассы/координат/даты, либо при любой
    сетевой/парсинг-ошибке — виджет в шаблоне просто не рендерится.
    """
    if stage is None:
        return None

    track = getattr(stage, "track", None)
    if track is None or track.latitude is None or track.longitude is None:
        return None

    start_date = getattr(stage, "start_date", None)
    if start_date is None:
        return None

    try:
        stage_date = timezone.localtime(start_date).date() if timezone.is_aware(start_date) else start_date.date()
        today = timezone.localdate()
        days_until = (stage_date - today).days

        if days_until < 0:
            # Архив: данные не меняются, кэшируем навсегда. Учти, что архивный
            # ERA5-эндпоинт Open-Meteo обычно отстаёт на несколько дней от
            # реального времени — для этапа, прошедшего 1-2 дня назад, запрос
            # может вернуть пустые данные; тогда корректно возвращаем None.
            cache_key = f"weather:stage:{stage.pk}:archive:{stage_date.isoformat()}"
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            data = fetch_archive_day_weather(track.latitude, track.longitude, stage_date)
            if data:
                cache.set(cache_key, data, timeout=None)
            return data

        category = "forecast" if days_until <= FORECAST_HORIZON_DAYS else "estimate"
        cache_key = f"weather:stage:{stage.pk}:{category}:{stage_date.isoformat()}:{today.isoformat()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        if category == "forecast":
            data = fetch_forecast_weather(track.latitude, track.longitude, stage_date)
        else:
            data = fetch_climatology_estimate(track.latitude, track.longitude, stage_date)

        if data:
            cache.set(cache_key, data)
        return data
    except Exception as e:
        logger.error(f"Неожиданная ошибка в get_stage_weather (stage={getattr(stage, 'pk', None)}): {e}")
        return None
