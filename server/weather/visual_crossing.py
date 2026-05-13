from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import requests
from django.conf import settings
from django.utils import timezone

from server.models import ExtendedWeatherSnapshot, SystemEvent
from server.monitoring import (
    record_provider_failure,
    record_provider_success,
    record_system_event,
)
from server.weather.geocoding import geocode_city
from server.weather.storage import normalize_coordinate

log = logging.getLogger("server.api")


class VisualCrossingUnavailable(RuntimeError):
    pass


class VisualCrossingClient:
    name = ExtendedWeatherSnapshot.SOURCE_VISUAL_CROSSING
    base_url = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"

    def is_enabled(self) -> bool:
        return bool(getattr(settings, "VISUAL_CROSSING_API_KEY", ""))

    def fetch_forecast(self, *, latitude: float, longitude: float, days: int) -> dict[str, Any]:
        api_key = getattr(settings, "VISUAL_CROSSING_API_KEY", "")
        if not api_key:
            raise VisualCrossingUnavailable("Visual Crossing API key is not configured")

        today = timezone.now().date()
        end_date = today + timedelta(days=days - 1)
        location = quote(f"{latitude},{longitude}", safe=",")
        url = f"{self.base_url}/{location}/{today.isoformat()}/{end_date.isoformat()}"
        response = requests.get(
            url,
            params={
                "unitGroup": "metric",
                "include": "days,hours",
                "contentType": "json",
                "key": api_key,
            },
            timeout=getattr(settings, "VISUAL_CROSSING_TIMEOUT_SECONDS", 10),
        )
        response.raise_for_status()
        return response.json()


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_optional(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _kph_to_ms(value: Any) -> float | None:
    parsed = _optional_float(value)
    if parsed is None:
        return None
    return round(parsed / 3.6, 2)


def normalize_visual_crossing_payload(
    payload: dict[str, Any],
    *,
    city: str,
    latitude: float,
    longitude: float,
    days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    daily = []
    hourly = []

    for day in (payload.get("days") or [])[:days]:
        date_value = str(day.get("datetime") or "")
        daily.append(
            {
                "date": date_value,
                "temp_min": _round_optional(_optional_float(day.get("tempmin")), 1),
                "temp_max": _round_optional(_optional_float(day.get("tempmax")), 1),
                "humidity": _round_optional(_optional_float(day.get("humidity")), 0),
                "wind_speed": _kph_to_ms(day.get("windspeed")),
                "precip_probability": _round_optional(_optional_float(day.get("precipprob")), 0),
                "conditions": day.get("conditions") or "",
            }
        )

        for hour in day.get("hours") or []:
            hour_value = str(hour.get("datetime") or "")
            hourly.append(
                {
                    "date": date_value,
                    "time": hour_value[:5] if hour_value else "",
                    "datetime": f"{date_value}T{hour_value}",
                    "temp": _round_optional(_optional_float(hour.get("temp")), 1),
                    "humidity": _round_optional(_optional_float(hour.get("humidity")), 0),
                    "wind_speed": _kph_to_ms(hour.get("windspeed")),
                    "precip_probability": _round_optional(_optional_float(hour.get("precipprob")), 0),
                    "conditions": hour.get("conditions") or "",
                }
            )

    resolved_location = payload.get("resolvedAddress") or city or f"{latitude},{longitude}"
    return daily, hourly, str(resolved_location)


class ExtendedWeatherService:
    source = ExtendedWeatherSnapshot.SOURCE_VISUAL_CROSSING

    def __init__(self, client: VisualCrossingClient | None = None):
        self.client = client or VisualCrossingClient()

    def get_extended_weather(
        self,
        *,
        user_id: int,
        city: str,
        latitude: float | None,
        longitude: float | None,
        days: int,
        request_id: str,
    ) -> dict[str, Any]:
        city, lat, lon = self._resolve_location(city=city, latitude=latitude, longitude=longitude)
        location_label = city or f"{lat},{lon}"
        now = timezone.now()

        self._event(
            "extended_weather_requested",
            request_id=request_id,
            user_id=user_id,
            location=location_label,
            cached=False,
        )

        snapshot = (
            ExtendedWeatherSnapshot.objects
            .filter(
                source=self.source,
                latitude=lat,
                longitude=lon,
                forecast_days=days,
                expires_at__gt=now,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        if snapshot is not None:
            self._event(
                "extended_weather_cache_hit",
                request_id=request_id,
                user_id=user_id,
                location=location_label,
                cached=True,
            )
            return self._snapshot_payload(snapshot, cached=True, request_id=request_id, user_id=user_id)

        self._event(
            "extended_weather_cache_miss",
            request_id=request_id,
            user_id=user_id,
            location=location_label,
            cached=False,
        )

        started = time.perf_counter()
        self._event(
            "visual_crossing_request_started",
            request_id=request_id,
            user_id=user_id,
            location=location_label,
            cached=False,
        )

        try:
            raw_payload = self.client.fetch_forecast(latitude=lat, longitude=lon, days=days)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            record_provider_success(name=self.source, duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            record_provider_failure(name=self.source, duration_ms=duration_ms, error_message=str(exc))
            self._event(
                "visual_crossing_request_failed",
                request_id=request_id,
                user_id=user_id,
                location=location_label,
                cached=False,
                level=SystemEvent.LEVEL_WARNING,
                extra={"duration_ms": duration_ms, "error": str(exc), "error_type": type(exc).__name__},
            )
            raise

        daily, hourly, resolved_location = normalize_visual_crossing_payload(
            raw_payload,
            city=city,
            latitude=lat,
            longitude=lon,
            days=days,
        )
        self._event(
            "visual_crossing_request_succeeded",
            request_id=request_id,
            user_id=user_id,
            location=location_label,
            cached=False,
            extra={"duration_ms": duration_ms, "days": len(daily)},
        )

        snapshot = ExtendedWeatherSnapshot.objects.create(
            city=city,
            location=resolved_location,
            latitude=lat,
            longitude=lon,
            source=self.source,
            forecast_days=days,
            payload_json=raw_payload,
            normalized_daily_json=daily,
            normalized_hourly_json=hourly,
            expires_at=now + timedelta(hours=6),
        )
        self._event(
            "extended_weather_saved",
            request_id=request_id,
            user_id=user_id,
            location=location_label,
            cached=False,
            extra={"snapshot_id": snapshot.pk, "expires_at": snapshot.expires_at.isoformat()},
        )
        return self._snapshot_payload(snapshot, cached=False, request_id=request_id, user_id=user_id)

    def _resolve_location(
        self,
        *,
        city: str,
        latitude: float | None,
        longitude: float | None,
    ) -> tuple[str, float, float]:
        city = (city or "").strip()
        if latitude is not None and longitude is not None:
            return city, normalize_coordinate(latitude), normalize_coordinate(longitude)

        if not city:
            raise ValueError("city or lat/lon query parameters are required")

        results = geocode_city(city=city, limit=1, language="ru")
        if not results:
            raise ValueError("city not found")

        place = results[0]
        resolved_city = ", ".join(part for part in [place.get("name"), place.get("country")] if part) or city
        return resolved_city, normalize_coordinate(place["latitude"]), normalize_coordinate(place["longitude"])

    def _snapshot_payload(
        self,
        snapshot: ExtendedWeatherSnapshot,
        *,
        cached: bool,
        request_id: str,
        user_id: int,
    ) -> dict[str, Any]:
        payload = {
            "source": self.source,
            "cached": cached,
            "request_id": request_id,
            "location": {
                "city": snapshot.city or snapshot.location,
                "lat": snapshot.latitude,
                "lon": snapshot.longitude,
            },
            "daily": snapshot.normalized_daily_json or [],
            "hourly": snapshot.normalized_hourly_json or [],
        }
        self._event(
            "extended_weather_returned",
            request_id=request_id,
            user_id=user_id,
            location=snapshot.city or snapshot.location,
            cached=cached,
            extra={"snapshot_id": snapshot.pk},
        )
        return payload

    def _event(
        self,
        event: str,
        *,
        request_id: str,
        user_id: int,
        location: str,
        cached: bool,
        level: str = SystemEvent.LEVEL_INFO,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "event": event,
            "user_id": user_id,
            "location": location,
            "source": self.source,
            "cached": cached,
            "request_id": request_id,
        }
        if extra:
            payload.update(extra)
        log.info(
            "%s request_id=%s user_id=%s location=%s source=%s cached=%s",
            event,
            request_id,
            user_id,
            location,
            self.source,
            cached,
        )
        record_system_event(
            event=event,
            source="weather",
            level=level,
            request_id=request_id,
            message=event.replace("_", " "),
            payload=payload,
        )
