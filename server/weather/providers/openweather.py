from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from server.weather.contracts import WeatherPoint, WeatherProvider

log = logging.getLogger(__name__)


class OpenWeatherProvider(WeatherProvider):
    name = "openweather"
    url = "https://api.openweathermap.org/data/2.5/weather"

    def is_enabled(self) -> bool:
        api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
        if os.getenv("TESTING_MODE", "0") == "1":
            log.info("OpenWeather is_enabled called key_present=%s", bool(api_key))
        return bool(api_key)
    
    def get_weather(self, latitude: float, longitude: float) -> WeatherPoint:
        api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENWEATHER_API_KEY is missing")

        params = {
            "lat": latitude,
            "lon": longitude,
            "appid": api_key,
            "units": "metric",
        }

        if os.getenv("TESTING_MODE", "0") == "1":
            log.info("OpenWeather request started")

        response = requests.get(self.url, params=params, timeout=10)

        if os.getenv("TESTING_MODE", "0") == "1":
            log.info("OpenWeather response status=%s", response.status_code)

        response.raise_for_status()
        data = response.json()

        observed_at = datetime.fromtimestamp(data.get("dt", 0), tz=timezone.utc)

        return WeatherPoint(
            latitude=float(latitude),
            longitude=float(longitude),
            temperature_c=float(data["main"]["temp"]),
            pressure_hpa=float(data["main"]["pressure"]),
            wind_speed_ms=float(data["wind"]["speed"]),
            precipitation_mm=float(data.get("rain", {}).get("1h", 0.0)),
            observed_at=observed_at,
            source=self.name,
        )
