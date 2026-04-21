from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from server.weather.contracts import WeatherPoint, WeatherProvider

log = logging.getLogger(__name__)


class OpenMeteoProvider(WeatherProvider):
    name = "openmeteo"
    url = "https://api.open-meteo.com/v1/forecast"

    def is_enabled(self) -> bool:
        return True

    def get_weather(self, latitude: float, longitude: float) -> WeatherPoint:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(
                [
                    "temperature_2m",
                    "pressure_msl",
                    "wind_speed_10m",
                    "precipitation",
                ]
            ),
            "timezone": "UTC",
        }

        if os.getenv("TESTING_MODE", "0") == "1":
            log.info("OpenMeteo request started")

        response = requests.get(self.url, params=params, timeout=10)

        if os.getenv("TESTING_MODE", "0") == "1":
            log.info("OpenMeteo response status=%s", response.status_code)

        response.raise_for_status()
        data = response.json()

        current = data["current"]
        observed_at = datetime.fromisoformat(current["time"].replace("Z", "+00:00")).astimezone(
            timezone.utc
        )

        return WeatherPoint(
            latitude=float(latitude),
            longitude=float(longitude),
            temperature_c=float(current["temperature_2m"]),
            pressure_hpa=float(current["pressure_msl"]),
            wind_speed_ms=float(current["wind_speed_10m"]),
            precipitation_mm=float(current["precipitation"]),
            observed_at=observed_at,
            source=self.name,
        )