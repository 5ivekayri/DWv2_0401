from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from server.weather.contracts import WeatherPoint, WeatherProvider

log = logging.getLogger(__name__)

class WeatherService:
    def __init__(self, providers: Iterable[WeatherProvider]):
        self.providers = list(providers)

    def get_weather(self, *, city: str | None, latitude: float | None, longitude: float | None) -> WeatherPoint:
        if city == "test":
            return WeatherPoint(
                latitude=0.0,
                longitude=0.0,
                temperature_c=0.0,
                pressure_hpa=0.0,
                wind_speed_ms=0.0,
                precipitation_mm=0.0,
                observed_at=datetime.now(timezone.utc),
                source="stub",
            )

        if latitude is None or longitude is None:
            raise ValueError("lat and lon are required (or city=test)")

        last_exc: Exception | None = None
        for p in self.providers:
            if not p.is_enabled():
                continue
            try:
                point = p.get_weather(latitude, longitude)
                log.info("Weather selected provider=%s", p.name)
                return point
            except Exception as exc:
                last_exc = exc
                log.warning("Provider %s failed: %s", p.name, exc)

        raise RuntimeError(f"All providers failed. last_error={last_exc}")
