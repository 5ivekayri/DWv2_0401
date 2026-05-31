from __future__ import annotations

from django.conf import settings

from server.iot.devices import device_summary
from server.models import IoTConfiguration
from server.monitoring import utc_iso


def get_iot_config() -> IoTConfiguration:
    defaults = {
        "connection_mode": getattr(settings, "IOT_CONNECTION_MODE", IoTConfiguration.CONNECTION_WIFI_ESP01),
        "serial_enabled": bool(getattr(settings, "SERIAL_BRIDGE_ENABLED", False)),
        "serial_port": getattr(settings, "SERIAL_BRIDGE_PORT", "COM3"),
        "baud_rate": int(getattr(settings, "SERIAL_BRIDGE_BAUD_RATE", 9600)),
        "mqtt_enabled": bool(getattr(settings, "MQTT_ENABLED", False)),
        "mqtt_host": getattr(settings, "MQTT_HOST", "127.0.0.1"),
        "mqtt_port": int(getattr(settings, "MQTT_PORT", 1883)),
        "mqtt_topic": getattr(settings, "MQTT_TOPIC", "weather/station"),
        "mqtt_username": getattr(settings, "MQTT_USERNAME", ""),
        "mqtt_password": getattr(settings, "MQTT_PASSWORD", ""),
    }
    defaults["serial_status"] = (
        IoTConfiguration.SERIAL_STATUS_DISCONNECTED
        if defaults["serial_enabled"]
        else IoTConfiguration.SERIAL_STATUS_DISABLED
    )
    defaults["mqtt_status"] = (
        IoTConfiguration.MQTT_STATUS_DISCONNECTED
        if defaults["mqtt_enabled"]
        else IoTConfiguration.MQTT_STATUS_DISABLED
    )
    config, _created = IoTConfiguration.objects.get_or_create(pk=1, defaults=defaults)
    return config


def serialize_iot_config(config: IoTConfiguration) -> dict:
    return {
        "connection_mode": config.connection_mode,
        "serial_port": config.serial_port,
        "baud_rate": config.baud_rate,
        "enabled": config.serial_enabled,
        "linked_device": device_summary(config.linked_device),
        "serial": {
            "enabled": config.serial_enabled,
            "port": config.serial_port,
            "baud_rate": config.baud_rate,
            "status": config.serial_status,
            "last_error": config.serial_last_error or None,
            "last_seen": utc_iso(config.serial_last_seen_at),
            "linked_device": device_summary(config.linked_device),
        },
        "mqtt": {
            "enabled": config.mqtt_enabled,
            "host": config.mqtt_host,
            "port": config.mqtt_port,
            "topic": config.mqtt_topic,
            "username": config.mqtt_username,
            "has_password": bool(config.mqtt_password),
            "status": config.mqtt_status,
            "last_error": config.mqtt_last_error or None,
            "last_seen": utc_iso(config.mqtt_last_seen_at),
        },
    }
