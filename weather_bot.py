import logging
import os
from collections import Counter
from dataclasses import dataclass
from datetime import date, time, timedelta
from statistics import mean
from typing import Iterable

import httpx
from telegram.ext import Application


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("weather-bot")

YO_COORDS = {"latitude": 56.6388, "longitude": 47.8908}
MSK_TIMEZONE = "Europe/Moscow"
TARGET_HOURS = (9, 12, 15, 18, 21)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODE_MAP = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь",
    51: "морось",
    53: "морось",
    55: "сильная морось",
    56: "ледяная морось",
    57: "ледяная морось",
    61: "дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "ледяной дождь",
    71: "снег",
    73: "снег",
    75: "сильный снег",
    77: "снежные зёрна",
    80: "ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "снег",
    86: "сильный снег",
    95: "гроза",
    96: "гроза с градом",
    99: "гроза с градом",
}


@dataclass
class HourWeather:
    hour: int
    temp_c: float
    wind_ms: float
    condition: str


async def fetch_hourly_forecast(target_date: date) -> list[HourWeather]:
    params = {
        "latitude": YO_COORDS["latitude"],
        "longitude": YO_COORDS["longitude"],
        "hourly": "temperature_2m,wind_speed_10m,weather_code",
        "timezone": MSK_TIMEZONE,
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "wind_speed_unit": "ms",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        payload = response.json()

    hourly = payload.get("hourly", {})
    times: list[str] = hourly.get("time", [])
    temps: list[float] = hourly.get("temperature_2m", [])
    winds: list[float] = hourly.get("wind_speed_10m", [])
    codes: list[int] = hourly.get("weather_code", [])

    weather_by_hour: list[HourWeather] = []
    for timestamp, temp, wind, code in zip(times, temps, winds, codes):
        hour = int(timestamp[-5:-3])
        if hour in TARGET_HOURS:
            weather_by_hour.append(
                HourWeather(
                    hour=hour,
                    temp_c=float(temp),
                    wind_ms=float(wind),
                    condition=WEATHER_CODE_MAP.get(int(code), "неизвестно"),
                )
            )

    return weather_by_hour


def build_message(day_label: str, items: Iterable[HourWeather]) -> str:
    items = list(items)
    if not items:
        return f"Погода в Йошкар-Оле на {day_label}:\n\nНе удалось получить данные."

    lines = [f"Погода в Йошкар-Оле на {day_label}:", ""]
    for row in items:
        lines.append(
            f"{row.hour}.00:{row.temp_c:.1f}°C, ветер {row.wind_ms:.1f} м/с, {row.condition}"
        )

    conditions = Counter(x.condition for x in items)
    total_condition = conditions.most_common(1)[0][0]
    avg_temp = mean(x.temp_c for x in items)
    avg_wind = mean(x.wind_ms for x in items)

    lines.extend(
        [
            "",
            "",
            f"Общее состояние: {total_condition}",
            f"Средняя температура: {avg_temp:.1f}°C",
            f"Средняя скорость ветра: {avg_wind:.1f} м/с",
        ]
    )
    return "\n".join(lines)


async def send_forecast(application: Application, channel_id: str, day_shift: int, day_label: str) -> None:
    target = date.today() + timedelta(days=day_shift)
    try:
        weather = await fetch_hourly_forecast(target)
        text = build_message(day_label, weather)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Cannot build forecast")
        text = f"Погода в Йошкар-Оле на {day_label}:\n\nОшибка получения прогноза: {exc}"

    await application.bot.send_message(chat_id=channel_id, text=text)


async def morning_job(context):
    await send_forecast(context.application, context.job.chat_id, day_shift=0, day_label="сегодня")


async def evening_job(context):
    await send_forecast(context.application, context.job.chat_id, day_shift=1, day_label="завтра")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "@grishalybitblondinok")

    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable")

    app = Application.builder().token(token).build()

    app.job_queue.run_daily(
        morning_job,
        time=time(hour=8, minute=0, second=0),
        days=(0, 1, 2, 3, 4, 5, 6),
        chat_id=channel_id,
        name="morning-forecast",
    )
    app.job_queue.run_daily(
        evening_job,
        time=time(hour=21, minute=0, second=0),
        days=(0, 1, 2, 3, 4, 5, 6),
        chat_id=channel_id,
        name="evening-forecast",
    )

    logger.info("Bot started. Channel: %s", channel_id)
    app.run_polling(allowed_updates=[])


if __name__ == "__main__":
    main()
