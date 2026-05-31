from __future__ import annotations

import importlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import timezone as dt_timezone
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from server.iot.config import get_iot_config
from server.iot.devices import find_device_by_station_id, record_device_reading
from server.models import IoTConfiguration, SystemEvent, WeatherStationReading
from server.monitoring import record_system_event
from server.weather.storage import store_station_reading_snapshot

log = logging.getLogger("server.api")


class MqttBridgeIgnoredMessage(ValueError):
    pass


@dataclass(frozen=True)
class MqttReadingPayload:
    station_id: str
    temperature_c: float
    humidity: float
    pressure_hpa: float | None
    wind_speed_ms: float
    precipitation_mm: float
    latitude: float | None
    longitude: float | None
    observed_at: Any
    raw_data: dict[str, Any]


def parse_mqtt_message(topic: str, payload: str | bytes) -> MqttReadingPayload:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MqttBridgeIgnoredMessage(f"invalid mqtt JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise MqttBridgeIgnoredMessage("mqtt JSON payload must be an object")
    if data.get("error"):
        raise MqttBridgeIgnoredMessage(f"mqtt sensor error: {data['error']}")

    station_id = str(data.get("station_id") or _station_id_from_topic(topic) or "").strip()
    if not station_id:
        raise MqttBridgeIgnoredMessage("station_id is required")
    if data.get("temperature_c") in (None, ""):
        raise MqttBridgeIgnoredMessage("temperature_c is required")
    if data.get("humidity") in (None, ""):
        raise MqttBridgeIgnoredMessage("humidity is required")

    return MqttReadingPayload(
        station_id=station_id,
        temperature_c=float(data["temperature_c"]),
        humidity=float(data["humidity"]),
        pressure_hpa=_optional_float(data.get("pressure_hpa")),
        wind_speed_ms=_optional_float(data.get("wind_speed_ms")) or 0.0,
        precipitation_mm=_optional_float(data.get("precipitation_mm")) or 0.0,
        latitude=_optional_float(data.get("latitude")),
        longitude=_optional_float(data.get("longitude")),
        observed_at=_parse_observed_at(data.get("observed_at") or data.get("timestamp") or data.get("time")),
        raw_data=data,
    )


class MqttArduinoListener:
    def __init__(self, config: IoTConfiguration | None = None):
        self.config = config or get_iot_config()

    def save_message(self, topic: str, payload: str | bytes, *, remote_ip: str = "") -> WeatherStationReading | None:
        try:
            parsed = parse_mqtt_message(topic, payload)
        except MqttBridgeIgnoredMessage as exc:
            self._mark_error(event="mqtt_parse_failed", message=str(exc), topic=topic, payload=payload, mark_status=False)
            return None
        except Exception as exc:
            self._mark_error(event="mqtt_parse_failed", message=str(exc), topic=topic, payload=payload, mark_status=False)
            return None

        device = find_device_by_station_id(parsed.station_id)

        try:
            reading = WeatherStationReading.objects.create(
                device=device,
                station_id=parsed.station_id,
                latitude=parsed.latitude,
                longitude=parsed.longitude,
                temperature_c=parsed.temperature_c,
                humidity=parsed.humidity,
                pressure_hpa=parsed.pressure_hpa,
                wind_speed_ms=parsed.wind_speed_ms,
                precipitation_mm=parsed.precipitation_mm,
                observed_at=parsed.observed_at,
                source=WeatherStationReading.SOURCE_MQTT,
                request_ip=remote_ip,
                raw_payload={
                    "source": WeatherStationReading.SOURCE_MQTT,
                    "topic": topic,
                    "payload": parsed.raw_data,
                },
            )
            record_device_reading(reading, ip_address=remote_ip)
            store_station_reading_snapshot(reading)
        except Exception as exc:
            self._mark_error(event="mqtt_save_failed", message=str(exc), topic=topic, payload=payload)
            return None

        now = timezone.now()
        self.config.mqtt_status = (
            IoTConfiguration.MQTT_STATUS_CONNECTED
            if self.config.mqtt_enabled
            else IoTConfiguration.MQTT_STATUS_DISABLED
        )
        self.config.mqtt_last_seen_at = now
        self.config.mqtt_last_error = ""
        self.config.save(update_fields=["mqtt_status", "mqtt_last_seen_at", "mqtt_last_error", "updated_at"])

        record_system_event(
            event="mqtt_message_received",
            source="mqtt",
            message=f"MQTT reading received from {parsed.station_id}",
            payload={
                "topic": topic,
                "station_id": parsed.station_id,
                "device_id": device.pk if device else None,
                "temperature_c": parsed.temperature_c,
                "humidity": parsed.humidity,
                "remote_ip": remote_ip,
            },
        )
        log.info(
            "mqtt_message_received topic=%s station_id=%s reading_id=%s temperature_c=%s humidity=%s",
            topic,
            parsed.station_id,
            reading.pk,
            parsed.temperature_c,
            parsed.humidity,
        )
        return reading

    def run_forever(self) -> None:
        try:
            mqtt = importlib.import_module("paho.mqtt.client")
        except ImportError:
            self._mark_error(event="mqtt_connection_failed", message="paho-mqtt is not installed")
            return

        record_system_event(
            event="mqtt_listener_started",
            source="mqtt",
            message="MQTT listener started",
            payload={
                "host": self.config.mqtt_host,
                "port": self.config.mqtt_port,
                "topic": self.config.mqtt_topic,
                "enabled": self.config.mqtt_enabled,
            },
        )
        log.info(
            "mqtt_listener_started host=%s port=%s topic=%s enabled=%s",
            self.config.mqtt_host,
            self.config.mqtt_port,
            self.config.mqtt_topic,
            self.config.mqtt_enabled,
        )

        while True:
            self.config.refresh_from_db()
            if not self.config.mqtt_enabled:
                self._set_status(IoTConfiguration.MQTT_STATUS_DISABLED, "")
                time.sleep(3)
                continue

            client = mqtt.Client(client_id="dark-weather-backend")
            if self.config.mqtt_username:
                client.username_pw_set(self.config.mqtt_username, self.config.mqtt_password or None)

            def on_connect(_client, _userdata, _flags, reason_code, *_args):
                if int(reason_code) == 0:
                    self._set_status(IoTConfiguration.MQTT_STATUS_CONNECTED, "")
                    _client.subscribe(self.config.mqtt_topic)
                    record_system_event(
                        event="mqtt_connected",
                        source="mqtt",
                        message=f"Connected to MQTT broker {self.config.mqtt_host}:{self.config.mqtt_port}",
                        payload={"topic": self.config.mqtt_topic},
                    )
                else:
                    self._mark_error(event="mqtt_connection_failed", message=f"MQTT connect failed: {reason_code}")

            def on_disconnect(_client, _userdata, reason_code, *_args):
                self._set_status(IoTConfiguration.MQTT_STATUS_DISCONNECTED, str(reason_code))
                record_system_event(
                    event="mqtt_disconnected",
                    source="mqtt",
                    level=SystemEvent.LEVEL_WARNING,
                    message=f"MQTT disconnected: {reason_code}",
                    payload={"host": self.config.mqtt_host, "port": self.config.mqtt_port},
                )

            def on_message(_client, _userdata, message):
                self.save_message(message.topic, message.payload)

            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.on_message = on_message

            try:
                client.connect(self.config.mqtt_host, self.config.mqtt_port, keepalive=60)
                client.loop_forever()
            except KeyboardInterrupt:
                self._set_status(IoTConfiguration.MQTT_STATUS_DISCONNECTED, "")
                record_system_event(event="mqtt_listener_stopped", source="mqtt", message="MQTT listener stopped")
                raise
            except Exception as exc:
                self._mark_error(event="mqtt_connection_failed", message=str(exc))
                time.sleep(3)

    def _set_status(self, status: str, error: str) -> None:
        self.config.mqtt_status = status
        self.config.mqtt_last_error = error[:1000]
        self.config.save(update_fields=["mqtt_status", "mqtt_last_error", "updated_at"])

    def _mark_error(
        self,
        *,
        event: str,
        message: str,
        topic: str = "",
        payload: str | bytes = "",
        mark_status: bool = True,
    ) -> None:
        if mark_status:
            self.config.mqtt_status = IoTConfiguration.MQTT_STATUS_ERROR
        self.config.mqtt_last_error = message[:1000]
        update_fields = ["mqtt_last_error", "updated_at"]
        if mark_status:
            update_fields.insert(0, "mqtt_status")
        self.config.save(update_fields=update_fields)
        record_system_event(
            event=event,
            source="mqtt",
            level=SystemEvent.LEVEL_WARNING,
            message=message,
            payload={"topic": topic, "payload": _payload_preview(payload)},
        )
        log.warning("%s topic=%s error=%s", event, topic, message)


def _station_id_from_topic(topic: str) -> str:
    chunks = [chunk for chunk in str(topic or "").split("/") if chunk]
    if len(chunks) >= 4 and chunks[-1] == "readings":
        return chunks[-2]
    return ""


def _payload_preview(payload: str | bytes) -> str:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
    return text[:1000]


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _parse_observed_at(value: Any):
    if not value:
        return timezone.now()
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValueError("invalid observed_at")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed
