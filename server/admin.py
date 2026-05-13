from django.contrib import admin

from .models import (
    DWDDevice,
    DWDDeviceEvent,
    DWDProviderApplication,
    DWDProvisioning,
    ExtendedWeatherSnapshot,
    IoTConfiguration,
    WeatherStationReading,
)


@admin.register(DWDProviderApplication)
class DWDProviderApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "email", "city", "status", "reviewed_by", "reviewed_at", "created_at")
    list_filter = ("status", "city", "created_at")
    search_fields = ("user__username", "user__email", "city", "comment")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DWDDevice)
class DWDDeviceAdmin(admin.ModelAdmin):
    list_display = ("id", "device_code", "station_id", "owner", "city", "firmware_type", "status", "is_enabled", "last_seen_at")
    list_filter = ("status", "is_enabled", "firmware_type", "city", "created_at")
    search_fields = ("device_code", "station_id", "owner__username", "owner__email", "city")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DWDProvisioning)
class DWDProvisioningAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "device",
        "firmware_type",
        "firmware_version",
        "delivery_status",
        "sent_by",
        "sent_at",
    )
    list_filter = ("firmware_type", "delivery_status", "delivery_channel", "created_at")
    search_fields = ("user__username", "user__email", "device__station_id", "firmware_version")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DWDDeviceEvent)
class DWDDeviceEventAdmin(admin.ModelAdmin):
    list_display = ("id", "device", "event_type", "severity", "ip_address", "created_at")
    list_filter = ("event_type", "severity", "created_at")
    search_fields = ("device__device_code", "device__station_id", "message", "ip_address")
    readonly_fields = ("created_at",)


@admin.register(ExtendedWeatherSnapshot)
class ExtendedWeatherSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "city", "source", "forecast_days", "latitude", "longitude", "created_at", "expires_at")
    list_filter = ("source", "forecast_days", "created_at", "expires_at")
    search_fields = ("city", "location", "source")
    readonly_fields = ("created_at",)


@admin.register(WeatherStationReading)
class WeatherStationReadingAdmin(admin.ModelAdmin):
    list_display = ("id", "device", "station_id", "source", "temperature_c", "humidity", "observed_at", "created_at")
    list_filter = ("source", "device", "station_id", "observed_at")
    search_fields = ("station_id", "source", "device__device_code", "device__city")
    readonly_fields = ("created_at",)


@admin.register(IoTConfiguration)
class IoTConfigurationAdmin(admin.ModelAdmin):
    list_display = ("id", "connection_mode", "linked_device", "serial_enabled", "serial_port", "baud_rate", "serial_status", "updated_at")
    readonly_fields = ("created_at", "updated_at", "serial_last_seen_at")
