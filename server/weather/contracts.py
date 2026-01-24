from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class WeatherPoint:
    latitude: float
    longitude: float
    temperature_c: float
    pressure_hpa: float
    wind_speed_ms: float
    precipitation_mm: float
    observed_at: datetime
    source: str


class WeatherProvider:
    name: str = "base"

    def is_enabled(self) -> bool:
        return True

    def get_weather(self, latitude: float, longitude: float) -> WeatherPoint:
        raise NotImplementedError
