from __future__ import annotations

import json
import logging
import time
import importlib
from dataclasses import dataclass
from datetime import timezone as dt_timezone
from typing import Any

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from server.iot.config import get_iot_config
from server.iot.devices import record_device_reading
from server.models import IoTConfiguration, SystemEvent, WeatherStationReading
from server.monitoring import record_system_event
from server.weather.storage import store_station_reading_snapshot

log = logging.getLogger("server.api")


class SerialBridgeError(RuntimeError):
    pass


class SerialBridgeIgnoredLine(ValueError):
    pass


@dataclass(frozen=True)
class SerialReadingPayload:
    station_id: str
    temperature_c: float
    humidity: float | None
    pressure_hpa: float | None
    wind_speed_ms: float
    precipitation_mm: float
    latitude: float | None
    longitude: float | None
    observed_at: Any
    raw_data: dict[str, Any]
    raw_temperature: float
    raw_humidity: float | None
    unit: str
    station_id_from_payload: str


def parse_serial_line(line: str) -> SerialReadingPayload:
    raw_line = (line or "").strip()
    if not raw_line:
        raise SerialBridgeIgnoredLine("empty serial line")

    if raw_line.startswith("{"):
        try:
            parsed = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise SerialBridgeIgnoredLine(f"invalid serial JSON: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise SerialBridgeIgnoredLine("serial JSON payload must be an object")
    else:
        parsed = {}
        for chunk in raw_line.split(";"):
            if not chunk.strip():
                continue
            if "=" not in chunk:
                raise SerialBridgeIgnoredLine(f"invalid key=value chunk: {chunk}")
            key, value = chunk.split("=", 1)
            parsed[key.strip()] = value.strip()

    if parsed.get("error"):
        raise SerialBridgeIgnoredLine(f"serial sensor error: {parsed['error']}")

    raw_temperature = _first(parsed, "temperature", "temperature_c", "temp")
    if raw_temperature in (None, ""):
        raise SerialBridgeIgnoredLine("temperature is required")

    raw_humidity = _first(parsed, "humidity", "hum")
    if raw_humidity in (None, ""):
        raise SerialBridgeIgnoredLine("humidity is required")

    unit = str(_first(parsed, "unit", "temperature_unit") or "celsius").strip().lower()
    temperature_c = _normalize_temperature(raw_temperature, unit)
    station_id_from_payload = str(_first(parsed, "station_id", "device_id") or "").strip()

    observed_at = _parse_observed_at(_first(parsed, "observed_at", "timestamp", "time"))
    return SerialReadingPayload(
        station_id=station_id_from_payload or "arduino-1",
        temperature_c=temperature_c,
        humidity=_optional_float(raw_humidity),
        pressure_hpa=_optional_float(_first(parsed, "pressure_hpa", "pressure")),
        wind_speed_ms=_optional_float(_first(parsed, "wind_speed_ms", "wind_speed")) or 0.0,
        precipitation_mm=_optional_float(_first(parsed, "precipitation_mm", "precipitation")) or 0.0,
        latitude=_optional_float(_first(parsed, "latitude", "lat")),
        longitude=_optional_float(_first(parsed, "longitude", "lon")),
        observed_at=observed_at,
        raw_data=parsed,
        raw_temperature=float(raw_temperature),
        raw_humidity=_optional_float(raw_humidity),
        unit=unit,
        station_id_from_payload=station_id_from_payload,
    )


class SerialArduinoReader:
    def __init__(self, config: IoTConfiguration | None = None):
        self.config = config or get_iot_config()
        self._last_empty_read_log_at: float | None = None

    def save_line(self, line: str) -> WeatherStationReading | None:
        try:
            payload = parse_serial_line(line)
        except SerialBridgeIgnoredLine as exc:
            self._mark_error(event="serial_bridge_parse_failed", message=str(exc), raw_line=line, mark_status=False)
            return None
        except Exception as exc:
            self._mark_error(event="serial_bridge_parse_failed", message=str(exc), raw_line=line, mark_status=False)
            return None

        device = self.config.linked_device
        station_id = payload.station_id
        if device is not None:
            if payload.station_id_from_payload and payload.station_id_from_payload != device.station_id:
                self._mark_error(
                    event="serial_bridge_parse_failed",
                    message=(
                        "serial station_id does not match linked device: "
                        f"{payload.station_id_from_payload} != {device.station_id}"
                    ),
                    raw_line=line,
                    mark_status=False,
                )
                return None
            station_id = device.station_id

        record_system_event(
            event="serial_bridge_reading_parsed",
            source="serial_bridge",
            message=f"Serial reading parsed for {station_id}",
            payload={
                "port": self.config.serial_port,
                "station_id": station_id,
                "linked_device_id": device.pk if device else None,
                "raw_line": line,
                "raw_temperature": payload.raw_temperature,
                "normalized_temperature": payload.temperature_c,
                "raw_humidity": payload.raw_humidity,
                "unit": payload.unit,
            },
        )
        log.info(
            "serial_bridge_reading_parsed port=%s station_id=%s raw_temperature=%s normalized_temperature=%s raw_humidity=%s",
            self.config.serial_port,
            station_id,
            payload.raw_temperature,
            payload.temperature_c,
            payload.raw_humidity,
        )

        try:
            reading = WeatherStationReading.objects.create(
                device=device,
                station_id=station_id,
                latitude=payload.latitude,
                longitude=payload.longitude,
                temperature_c=payload.temperature_c,
                humidity=payload.humidity,
                pressure_hpa=payload.pressure_hpa,
                wind_speed_ms=payload.wind_speed_ms,
                precipitation_mm=payload.precipitation_mm,
                observed_at=payload.observed_at,
                source=WeatherStationReading.SOURCE_SERIAL_BRIDGE,
                raw_payload={
                    "source": WeatherStationReading.SOURCE_SERIAL_BRIDGE,
                    "raw_line": line,
                    "payload": payload.raw_data,
                    "linked_device_id": device.pk if device else None,
                    "raw_temperature": payload.raw_temperature,
                    "normalized_temperature": payload.temperature_c,
                    "raw_humidity": payload.raw_humidity,
                    "unit": payload.unit,
                },
            )
            record_device_reading(reading)
            store_station_reading_snapshot(reading)
        except Exception as exc:
            self._mark_error(event="serial_bridge_save_failed", message=str(exc), raw_line=line)
            return None

        now = timezone.now()
        self.config.serial_status = (
            IoTConfiguration.SERIAL_STATUS_CONNECTED
            if self.config.serial_enabled
            else IoTConfiguration.SERIAL_STATUS_DISABLED
        )
        self.config.serial_last_seen_at = now
        self.config.serial_last_error = ""
        self.config.save(update_fields=["serial_status", "serial_last_seen_at", "serial_last_error", "updated_at"])

        record_system_event(
            event="serial_bridge_reading_received",
            source="serial_bridge",
            message=f"Serial reading received from {payload.station_id}",
            payload={
                "port": self.config.serial_port,
                "station_id": station_id,
                "linked_device_id": device.pk if device else None,
                "temperature": payload.temperature_c,
                "humidity": payload.humidity,
                "source": WeatherStationReading.SOURCE_SERIAL_BRIDGE,
            },
        )
        log.info(
            "serial_bridge_reading_received port=%s station_id=%s temperature=%s humidity=%s",
            self.config.serial_port,
            station_id,
            payload.temperature_c,
            payload.humidity,
        )
        return reading

    def run_forever(self, *, reconnect_delay_seconds: float = 3.0) -> None:
        record_system_event(
            event="serial_bridge_started",
            source="serial_bridge",
            message="Serial Bridge reader started",
            payload={
                "port": self.config.serial_port,
                "baud_rate": self.config.baud_rate,
                "linked_device_id": self.config.linked_device_id,
                "enabled": self.config.serial_enabled,
            },
        )
        log.info(
            "serial_bridge_started port=%s baud_rate=%s linked_device_id=%s enabled=%s",
            self.config.serial_port,
            self.config.baud_rate,
            self.config.linked_device_id,
            self.config.serial_enabled,
        )
        try:
            while True:
                self.config.refresh_from_db()
                if not self.config.serial_enabled:
                    self._set_status(IoTConfiguration.SERIAL_STATUS_DISABLED, "")
                    time.sleep(reconnect_delay_seconds)
                    continue
                self._read_loop_once()
        except KeyboardInterrupt:
            self._set_status(IoTConfiguration.SERIAL_STATUS_DISCONNECTED, "")
            record_system_event(
                event="serial_bridge_stopped",
                source="serial_bridge",
                message="Serial Bridge reader stopped",
                payload={"port": self.config.serial_port},
            )

    def _read_loop_once(self) -> None:
        try:
            serial = importlib.import_module("serial")
        except ImportError as exc:
            self._mark_error(event="serial_bridge_port_error", message="pyserial is not installed")
            time.sleep(3)
            return

        try:
            timeout_seconds = getattr(settings, "SERIAL_BRIDGE_TIMEOUT_SECONDS", 2)
            record_system_event(
                event="serial_bridge_open_attempted",
                source="serial_bridge",
                message=f"Opening serial port {self.config.serial_port}",
                payload={
                    "port": self.config.serial_port,
                    "baud_rate": self.config.baud_rate,
                    "timeout_seconds": timeout_seconds,
                    "linked_device_id": self.config.linked_device_id,
                },
            )
            log.info(
                "serial_bridge_open_attempted port=%s baud_rate=%s timeout_seconds=%s linked_device_id=%s",
                self.config.serial_port,
                self.config.baud_rate,
                timeout_seconds,
                self.config.linked_device_id,
            )
            with serial.Serial(
                self.config.serial_port,
                self.config.baud_rate,
                timeout=timeout_seconds,
            ) as connection:
                self._set_status(IoTConfiguration.SERIAL_STATUS_CONNECTED, "")
                record_system_event(
                    event="serial_bridge_connected",
                    source="serial_bridge",
                    message=f"Serial Bridge connected to {self.config.serial_port}",
                    payload={"port": self.config.serial_port, "baud_rate": self.config.baud_rate},
                )
                while self.config.serial_enabled:
                    self.config.refresh_from_db()
                    if not self.config.serial_enabled:
                        break
                    raw = connection.readline()
                    if not raw:
                        self._log_empty_read()
                        continue
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line:
                        self._log_raw_line(raw=raw, line=line)
                        self.save_line(line)
        except Exception as exc:
            self._mark_error(event="serial_bridge_port_error", message=str(exc))
            record_system_event(
                event="serial_bridge_disconnected",
                source="serial_bridge",
                level=SystemEvent.LEVEL_WARNING,
                message=f"Serial Bridge disconnected from {self.config.serial_port}",
                payload={"port": self.config.serial_port, "error": str(exc)},
            )
            time.sleep(3)

    def _log_empty_read(self) -> None:
        now = time.monotonic()
        interval = float(getattr(settings, "SERIAL_BRIDGE_EMPTY_READ_LOG_INTERVAL_SECONDS", 30))
        if self._last_empty_read_log_at is not None and now - self._last_empty_read_log_at < interval:
            return
        self._last_empty_read_log_at = now
        record_system_event(
            event="serial_bridge_readline_timeout",
            source="serial_bridge",
            level=SystemEvent.LEVEL_WARNING,
            message=f"No serial data received from {self.config.serial_port}",
            payload={
                "port": self.config.serial_port,
                "baud_rate": self.config.baud_rate,
                "timeout_seconds": getattr(settings, "SERIAL_BRIDGE_TIMEOUT_SECONDS", 2),
                "linked_device_id": self.config.linked_device_id,
            },
        )
        log.warning(
            "serial_bridge_readline_timeout port=%s baud_rate=%s timeout_seconds=%s linked_device_id=%s",
            self.config.serial_port,
            self.config.baud_rate,
            getattr(settings, "SERIAL_BRIDGE_TIMEOUT_SECONDS", 2),
            self.config.linked_device_id,
        )

    def _log_raw_line(self, *, raw: bytes, line: str) -> None:
        record_system_event(
            event="serial_bridge_raw_line_received",
            source="serial_bridge",
            message=f"Raw serial line received from {self.config.serial_port}",
            payload={
                "port": self.config.serial_port,
                "baud_rate": self.config.baud_rate,
                "raw_line": line,
                "raw_bytes_length": len(raw),
                "linked_device_id": self.config.linked_device_id,
            },
        )
        log.info(
            "serial_bridge_raw_line_received port=%s baud_rate=%s raw_bytes_length=%s raw_line=%s linked_device_id=%s",
            self.config.serial_port,
            self.config.baud_rate,
            len(raw),
            line,
            self.config.linked_device_id,
        )

    def _set_status(self, status: str, error: str) -> None:
        self.config.serial_status = status
        self.config.serial_last_error = error
        self.config.save(update_fields=["serial_status", "serial_last_error", "updated_at"])

    def _mark_error(self, *, event: str, message: str, raw_line: str = "", mark_status: bool = True) -> None:
        if mark_status:
            self.config.serial_status = IoTConfiguration.SERIAL_STATUS_ERROR
        self.config.serial_last_error = message[:1000]
        update_fields = ["serial_last_error", "updated_at"]
        if mark_status:
            update_fields.insert(0, "serial_status")
        self.config.save(update_fields=update_fields)
        record_system_event(
            event=event,
            source="serial_bridge",
            level=SystemEvent.LEVEL_WARNING,
            message=message,
            payload={"port": self.config.serial_port, "raw_line": raw_line},
        )
        log.warning("%s port=%s error=%s", event, self.config.serial_port, message)


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _normalize_temperature(value: Any, unit: str) -> float:
    temperature = float(value)
    if unit in {"fahrenheit", "f"}:
        return round((temperature - 32.0) * 5.0 / 9.0, 4)
    if unit not in {"celsius", "c", ""}:
        raise SerialBridgeIgnoredLine(f"unsupported temperature unit: {unit}")
    return temperature


def _parse_observed_at(value: Any):
    if not value:
        return timezone.now()
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValueError("invalid observed_at")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed
