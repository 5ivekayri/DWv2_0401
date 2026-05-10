from __future__ import annotations

import logging
from datetime import timedelta, timezone as dt_timezone
from typing import Any

from django.db import DatabaseError
from django.db.models import F
from django.utils import timezone

from server.models import ProviderHealth, RaceRun, SystemEvent, WeatherStationReading

log = logging.getLogger("server.monitoring")

KNOWN_PROVIDERS = ("yandex", "openweather", "openmeteo")


def utc_iso(value) -> str | None:
    if value is None:
        return None
    return value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


def record_system_event(
    *,
    event: str,
    source: str,
    level: str = SystemEvent.LEVEL_INFO,
    message: str = "",
    request_id: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        SystemEvent.objects.create(
            timestamp=timezone.now(),
            level=level,
            event=event,
            message=message,
            request_id=request_id or "",
            source=source,
            payload=payload or {},
        )
    except Exception as exc:
        log.debug("monitoring_event_write_failed event=%s error=%s", event, exc)


def ensure_provider_health(name: str, *, enabled: bool | None = None) -> ProviderHealth | None:
    defaults: dict[str, Any] = {}
    if enabled is not None:
        defaults["enabled"] = enabled
        if not enabled:
            defaults["status"] = ProviderHealth.STATUS_NOT_CONFIGURED
            defaults["last_error_message"] = "API key is not configured"

    try:
        obj, _created = ProviderHealth.objects.get_or_create(name=name, defaults=defaults)
        if defaults:
            for key, value in defaults.items():
                setattr(obj, key, value)
            obj.save(update_fields=[*defaults.keys(), "updated_at"])
        return obj
    except Exception as exc:
        log.debug("provider_health_ensure_failed provider=%s error=%s", name, exc)
        return None


def mark_provider_config(name: str, *, enabled: bool, message: str | None = None) -> None:
    obj = ensure_provider_health(name)
    if obj is None:
        return

    obj.enabled = enabled
    if enabled and obj.status == ProviderHealth.STATUS_NOT_CONFIGURED:
        obj.status = ProviderHealth.STATUS_OK
        obj.last_error_message = None
    elif not enabled:
        obj.status = ProviderHealth.STATUS_NOT_CONFIGURED
        obj.last_error_message = message or "API key is not configured"
    obj.save(update_fields=["enabled", "status", "last_error_message", "updated_at"])


def record_provider_success(*, name: str, duration_ms: float) -> None:
    ensure_provider_health(name, enabled=True)
    try:
        ProviderHealth.objects.filter(name=name).update(
            enabled=True,
            status=ProviderHealth.STATUS_OK,
            last_success_at=timezone.now(),
            last_error_message=None,
            last_response_ms=duration_ms,
            response_count=F("response_count") + 1,
            total_response_ms=F("total_response_ms") + duration_ms,
            success_count=F("success_count") + 1,
        )
    except DatabaseError as exc:
        log.debug("provider_success_write_failed provider=%s error=%s", name, exc)


def record_provider_failure(*, name: str, duration_ms: float | None, error_message: str) -> None:
    ensure_provider_health(name, enabled=True)
    try:
        updates = {
            "enabled": True,
            "status": ProviderHealth.STATUS_ERROR,
            "last_error_at": timezone.now(),
            "last_error_message": error_message[:1000],
            "last_response_ms": duration_ms,
            "error_count": F("error_count") + 1,
        }
        if duration_ms is not None:
            updates["response_count"] = F("response_count") + 1
            updates["total_response_ms"] = F("total_response_ms") + duration_ms
        ProviderHealth.objects.filter(name=name).update(**updates)
    except DatabaseError as exc:
        log.debug("provider_failure_write_failed provider=%s error=%s", name, exc)


def record_provider_win(*, name: str) -> None:
    ensure_provider_health(name, enabled=True)
    try:
        ProviderHealth.objects.filter(name=name).update(win_count=F("win_count") + 1)
    except DatabaseError as exc:
        log.debug("provider_win_write_failed provider=%s error=%s", name, exc)


def record_race_run(
    *,
    request_id: str,
    started_at,
    duration_ms: float | None,
    winner: str = "",
    status: str = RaceRun.STATUS_SUCCESS,
    errors: list[dict[str, Any]] | None = None,
) -> None:
    try:
        RaceRun.objects.create(
            request_id=request_id,
            started_at=started_at,
            duration_ms=duration_ms,
            winner=winner or "",
            status=status,
            errors=errors or [],
        )
    except Exception as exc:
        log.debug("race_run_write_failed request_id=%s error=%s", request_id, exc)


def provider_health_to_payload(obj: ProviderHealth) -> dict[str, Any]:
    return {
        "name": obj.name,
        "enabled": obj.enabled,
        "status": obj.status,
        "last_success_at": utc_iso(obj.last_success_at),
        "last_error_at": utc_iso(obj.last_error_at),
        "last_error_message": obj.last_error_message,
        "last_response_ms": obj.last_response_ms,
        "success_count": obj.success_count,
        "error_count": obj.error_count,
        "win_count": obj.win_count,
    }


def race_run_to_payload(obj: RaceRun) -> dict[str, Any]:
    return {
        "request_id": obj.request_id,
        "winner": obj.winner or None,
        "started_at": utc_iso(obj.started_at),
        "duration_ms": obj.duration_ms,
    }


def system_event_to_payload(obj: SystemEvent) -> dict[str, Any]:
    return {
        "timestamp": utc_iso(obj.timestamp),
        "level": obj.level,
        "event": obj.event,
        "message": obj.message,
        "request_id": obj.request_id or None,
        "source": obj.source,
    }


def get_latest_station_status(*, offline_after_seconds: int) -> dict[str, Any]:
    latest = WeatherStationReading.objects.order_by("-created_at", "-observed_at").first()
    if latest is None:
        return {
            "status": "offline",
            "last_seen": None,
            "last_reading": None,
        }

    last_seen = latest.created_at
    is_online = timezone.now() - last_seen <= timedelta(seconds=offline_after_seconds)
    if not is_online:
        record_system_event(
            event="iot_station_offline",
            source="iot",
            level=SystemEvent.LEVEL_WARNING,
            message=f"Station {latest.station_id} has no fresh readings",
            payload={"station_id": latest.station_id, "last_seen": utc_iso(last_seen)},
        )

    return {
        "status": "online" if is_online else "offline",
        "last_seen": utc_iso(last_seen),
        "last_reading": {
            "temperature": latest.temperature_c,
            "humidity": latest.humidity,
        },
    }
