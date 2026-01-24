from __future__ import annotations

from server.weather.providers.openmeteo import OpenMeteoProvider
from server.weather.service import WeatherService

def build_weather_service() -> WeatherService:
    providers = [
        OpenMeteoProvider(),
    ]
    return WeatherService(providers)
