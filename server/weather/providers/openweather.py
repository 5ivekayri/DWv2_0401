from __future__ import annotations

import os
import logging
from datetime import datetime, timezone

import requests

from server.weather.contracts import WeatherPoint, WeatherProvider

log = logging.getLogger(__name__)

class OpenWeatherProvider(WeatherProvider):
    name = "openweather"
    url = "https://api.openweathermap.org/data/2.5/weather"

    def get_weather(self, latitude: float, longitude: float) -> WeatherPoint:
        api_key = os.getenv("OPENWEATHER_API_KEY", "")
        params = {
            "lat": latitude,
            "lon": longitude,
            "appid": api_key,
            "units": "metric",
        }

        if os.getenv("TESTING_MODE", "0") == "1":
            log.info("OpenWeather GET %s params=%s", self.url, params)

        r = requests.get(self.url, params=params, timeout=10)

        if os.getenv("TESTING_MODE", "0") == "1":
            log.info("OpenWeather status=%s body=%s", r.status_code, r.text[:500])

        r.raise_for_status()
        data = r.json()

        observed_at = datetime.fromtimestamp(data.get("dt", 0), tz=timezone.utc)

        return WeatherPoint(
            latitude=latitude,
            longitude=longitude,
            temperature_c=float(data["main"]["temp"]),
            pressure_hpa=float(data["main"]["pressure"]),
            wind_speed_ms=float(data["wind"]["speed"]),
            precipitation_mm=float(data.get("rain", {}).get("1h", 0.0)),
            observed_at=observed_at,
            source=self.name,
        )