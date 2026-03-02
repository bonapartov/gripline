import requests
import datetime
import logging

logger = logging.getLogger(__name__)

def fetch_weather_data(latitude, longitude, target_date, target_time):
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
