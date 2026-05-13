from __future__ import annotations

from typing import Any

from django.utils import timezone

from server.models import DWDDevice, DWDDeviceEvent, WeatherStationReading
from server.monitoring import utc_iso


def device_display_name(device: DWDDevice) -> str:
    return device.device_code or device.station_id


def device_summary(device: DWDDevice | None) -> dict[str, Any] | None:
    if device is None:
        return None
    return {
        "id": device.pk,
        "name": device_display_name(device),
        "station_id": device.station_id,
        "city": device.city,
        "owner": device.owner.get_username() if device.owner_id else "",
    }


def device_station_payload(device: DWDDevice, *, status: str | None = None) -> dict[str, Any]:
    return {
        "id": device.pk,
        "name": device_display_name(device),
        "station_id": device.station_id,
        "connection_mode": device.firmware_type or "",
        "status": status or device.status,
        "last_seen": utc_iso(device.last_seen_at),
        "city": device.city,
    }


def find_device_by_station_id(station_id: str) -> DWDDevice | None:
    if not station_id:
        return None
    return DWDDevice.objects.select_related("owner").filter(station_id=station_id).first()


def record_device_reading(reading: WeatherStationReading, *, ip_address: str | None = None) -> None:
    device = reading.device
    if device is None:
        return

    now = timezone.now()
    device.last_seen_at = now
    device.last_data_at = reading.created_at or now
    if ip_address:
        device.ip_address = ip_address
        device.last_request_at = now
    device.last_error = ""
    device.last_error_at = None
    fields = ["last_seen_at", "last_data_at", "last_error", "last_error_at", "updated_at"]
    if ip_address:
        fields.extend(["ip_address", "last_request_at"])
    device.save(update_fields=fields)

    DWDDeviceEvent.objects.create(
        device=device,
        event_type=DWDDeviceEvent.EVENT_DATA_INGEST,
        severity=DWDDeviceEvent.SEVERITY_INFO,
        message=f"Reading received from {reading.source}",
        ip_address=ip_address or "",
    )
