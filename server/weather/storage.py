from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.cache import cache
from django.core.cache.backends.base import InvalidCacheBackendError
from django.db import DatabaseError

from server.models import WeatherHourlySnapshot, WeatherStationReading
from server.weather.contracts import WeatherPoint


def get_hour_bucket(moment: datetime | None = None) -> datetime:
    value = moment or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def normalize_coordinate(value: float) -> float:
    return round(float(value), 4)


def get_weather_cache_key(
    *,
    latitude: float,
    longitude: float,
    hour_bucket: datetime,
    data_source: str = WeatherHourlySnapshot.SOURCE_EXTERNAL_API,
) -> str:
    lat = normalize_coordinate(latitude)
    lon = normalize_coordinate(longitude)
    hour = hour_bucket.astimezone(timezone.utc).strftime("%Y%m%d%H")
    return f"weather:{data_source}:{lat}:{lon}:{hour}"


def get_weather_cache_ttl(hour_bucket: datetime) -> int:
    configured_ttl = int(getattr(settings, "WEATHER_CACHE_TTL_SECONDS", 3600))
    next_hour = hour_bucket.astimezone(timezone.utc) + timedelta(hours=1)
    seconds_until_next_hour = int((next_hour - datetime.now(timezone.utc)).total_seconds())
    return max(1, min(configured_ttl, seconds_until_next_hour if seconds_until_next_hour > 0 else 1))


def point_to_payload(point: WeatherPoint) -> dict:
    payload = asdict(point)
    payload["observed_at"] = (
        point.observed_at.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return payload


def snapshot_to_payload(snapshot: WeatherHourlySnapshot) -> dict:
    payload = dict(snapshot.raw_payload or {})
    payload.update(
        {
            "latitude": snapshot.latitude,
            "longitude": snapshot.longitude,
            "temperature_c": snapshot.temperature_c,
            "pressure_hpa": snapshot.pressure_hpa,
            "wind_speed_ms": snapshot.wind_speed_ms,
            "precipitation_mm": snapshot.precipitation_mm,
            "observed_at": snapshot.observed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": snapshot.provider,
        }
    )
    return payload


def get_cached_weather_payload(*, latitude: float, longitude: float, hour_bucket: datetime) -> dict | None:
    key = get_weather_cache_key(latitude=latitude, longitude=longitude, hour_bucket=hour_bucket)
    try:
        value = cache.get(key)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def set_cached_weather_payload(*, latitude: float, longitude: float, hour_bucket: datetime, payload: dict) -> None:
    key = get_weather_cache_key(latitude=latitude, longitude=longitude, hour_bucket=hour_bucket)
    try:
        cache.set(key, payload, timeout=get_weather_cache_ttl(hour_bucket))
    except (InvalidCacheBackendError, Exception):
        return


def get_stored_weather_payload(*, latitude: float, longitude: float, hour_bucket: datetime) -> dict | None:
    lat = normalize_coordinate(latitude)
    lon = normalize_coordinate(longitude)
    try:
        snapshot = (
            WeatherHourlySnapshot.objects
            .filter(
                latitude=lat,
                longitude=lon,
                hour_bucket=hour_bucket,
                data_source=WeatherHourlySnapshot.SOURCE_EXTERNAL_API,
            )
            .first()
        )
    except DatabaseError:
        return None

    if not snapshot:
        return None

    payload = snapshot_to_payload(snapshot)
    set_cached_weather_payload(latitude=lat, longitude=lon, hour_bucket=hour_bucket, payload=payload)
    return payload


def store_weather_point(
    *,
    point: WeatherPoint,
    city: str | None,
    hour_bucket: datetime,
    data_source: str = WeatherHourlySnapshot.SOURCE_EXTERNAL_API,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict:
    lat = normalize_coordinate(point.latitude if latitude is None else latitude)
    lon = normalize_coordinate(point.longitude if longitude is None else longitude)
    payload = point_to_payload(point)

    WeatherHourlySnapshot.objects.update_or_create(
        latitude=lat,
        longitude=lon,
        hour_bucket=hour_bucket,
        data_source=data_source,
        defaults={
            "city": (city or "").strip(),
            "temperature_c": point.temperature_c,
            "pressure_hpa": point.pressure_hpa,
            "wind_speed_ms": point.wind_speed_ms,
            "precipitation_mm": point.precipitation_mm,
            "observed_at": point.observed_at,
            "provider": point.source,
            "raw_payload": payload,
        },
    )
    set_cached_weather_payload(latitude=lat, longitude=lon, hour_bucket=hour_bucket, payload=payload)
    return payload


def station_reading_to_payload(reading: WeatherStationReading) -> dict:
    return {
        "id": reading.id,
        "device_id": reading.device_id,
        "station_id": reading.station_id,
        "latitude": reading.latitude,
        "longitude": reading.longitude,
        "temperature": reading.temperature_c,
        "temperature_c": reading.temperature_c,
        "humidity": reading.humidity,
        "pressure_hpa": reading.pressure_hpa,
        "wind_speed_ms": reading.wind_speed_ms,
        "precipitation_mm": reading.precipitation_mm,
        "observed_at": reading.observed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "created_at": reading.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": reading.source,
        "data_source": WeatherHourlySnapshot.SOURCE_IOT_MQTT,
    }


def store_station_reading_snapshot(reading: WeatherStationReading) -> None:
    if reading.latitude is None or reading.longitude is None:
        return

    lat = normalize_coordinate(reading.latitude)
    lon = normalize_coordinate(reading.longitude)
    hour_bucket = get_hour_bucket(reading.observed_at)
    payload = station_reading_to_payload(reading)

    WeatherHourlySnapshot.objects.update_or_create(
        latitude=lat,
        longitude=lon,
        hour_bucket=hour_bucket,
        data_source=WeatherHourlySnapshot.SOURCE_IOT_MQTT,
        defaults={
            "city": "",
            "temperature_c": reading.temperature_c,
            "pressure_hpa": reading.pressure_hpa,
            "wind_speed_ms": reading.wind_speed_ms,
            "precipitation_mm": reading.precipitation_mm,
            "observed_at": reading.observed_at,
            "provider": reading.source,
            "raw_payload": payload,
        },
    )
