from __future__ import annotations

from django.conf import settings
from django.db import models


class AIOutfitRecommendation(models.Model):
    city = models.CharField(max_length=128)
    hour_bucket = models.DateTimeField(db_index=True)

    temperature_c = models.FloatField()
    humidity = models.FloatField()
    wind_speed_ms = models.FloatField()
    precipitation_mm = models.FloatField()
    condition = models.CharField(max_length=128, blank=True, default="")

    model_name = models.CharField(max_length=128)
    prompt_version = models.CharField(max_length=32, default="v1")
    recommendation_text = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-hour_bucket", "-created_at"]
        indexes = [
            models.Index(fields=["city", "hour_bucket"]),
        ]

    def __str__(self) -> str:
        return f"{self.city} @ {self.hour_bucket.isoformat()}"


class WeatherHourlySnapshot(models.Model):
    SOURCE_EXTERNAL_API = "external_api"
    SOURCE_IOT_MQTT = "iot_mqtt"

    DATA_SOURCE_CHOICES = [
        (SOURCE_EXTERNAL_API, "External API"),
        (SOURCE_IOT_MQTT, "IoT MQTT"),
    ]

    city = models.CharField(max_length=128, blank=True, default="")
    latitude = models.FloatField()
    longitude = models.FloatField()
    hour_bucket = models.DateTimeField(db_index=True)

    temperature_c = models.FloatField()
    pressure_hpa = models.FloatField(null=True, blank=True)
    wind_speed_ms = models.FloatField()
    precipitation_mm = models.FloatField()
    observed_at = models.DateTimeField()

    provider = models.CharField(max_length=64)
    data_source = models.CharField(
        max_length=32,
        choices=DATA_SOURCE_CHOICES,
        default=SOURCE_EXTERNAL_API,
    )
    raw_payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-hour_bucket", "-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["latitude", "longitude", "hour_bucket", "data_source"],
                name="unique_weather_hourly_snapshot",
            )
        ]
        indexes = [
            models.Index(fields=["latitude", "longitude", "hour_bucket"]),
            models.Index(fields=["data_source", "hour_bucket"]),
        ]

    def __str__(self) -> str:
        return f"{self.data_source}:{self.latitude},{self.longitude} @ {self.hour_bucket.isoformat()}"


class ExtendedWeatherSnapshot(models.Model):
    SOURCE_VISUAL_CROSSING = "visual_crossing"

    city = models.CharField(max_length=128, blank=True, default="")
    location = models.CharField(max_length=256, blank=True, default="")
    latitude = models.FloatField()
    longitude = models.FloatField()
    source = models.CharField(max_length=64, default=SOURCE_VISUAL_CROSSING, db_index=True)
    forecast_days = models.PositiveSmallIntegerField(default=7)
    payload_json = models.JSONField(default=dict, blank=True)
    normalized_daily_json = models.JSONField(default=list, blank=True)
    normalized_hourly_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["source", "latitude", "longitude", "forecast_days", "expires_at"]),
            models.Index(fields=["city", "source", "forecast_days", "expires_at"]),
        ]

    def __str__(self) -> str:
        label = self.city or self.location or f"{self.latitude},{self.longitude}"
        return f"{self.source}:{label} {self.forecast_days}d"


class WeatherStationReading(models.Model):
    SOURCE_SERIAL_BRIDGE = "serial_bridge"
    SOURCE_WIFI_ESP01 = "wifi_esp01"
    SOURCE_ETHERNET_SHIELD = "ethernet_shield"

    SOURCE_CHOICES = [
        (SOURCE_SERIAL_BRIDGE, "Serial Bridge"),
        (SOURCE_WIFI_ESP01, "ESP-01 Wi-Fi"),
        (SOURCE_ETHERNET_SHIELD, "Ethernet Shield"),
    ]

    device = models.ForeignKey(
        "DWDDevice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="readings",
    )
    station_id = models.CharField(max_length=64, db_index=True, default="arduino-1")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    temperature_c = models.FloatField()
    humidity = models.FloatField(null=True, blank=True)
    pressure_hpa = models.FloatField(null=True, blank=True)
    wind_speed_ms = models.FloatField(default=0.0)
    precipitation_mm = models.FloatField(default=0.0)

    observed_at = models.DateTimeField(db_index=True)
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES, default=SOURCE_WIFI_ESP01, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_at", "-created_at"]
        indexes = [
            models.Index(fields=["device", "observed_at"]),
            models.Index(fields=["station_id", "observed_at"]),
            models.Index(fields=["source", "observed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.station_id} @ {self.observed_at.isoformat()}"


class IoTConfiguration(models.Model):
    CONNECTION_SERIAL_BRIDGE = "serial_bridge"
    CONNECTION_WIFI_ESP01 = "wifi_esp01"
    CONNECTION_ETHERNET_SHIELD = "ethernet_shield"

    CONNECTION_MODE_CHOICES = [
        (CONNECTION_SERIAL_BRIDGE, "Serial Bridge"),
        (CONNECTION_WIFI_ESP01, "ESP-01 Wi-Fi"),
        (CONNECTION_ETHERNET_SHIELD, "Ethernet Shield"),
    ]

    SERIAL_STATUS_DISABLED = "disabled"
    SERIAL_STATUS_DISCONNECTED = "disconnected"
    SERIAL_STATUS_CONNECTED = "connected"
    SERIAL_STATUS_ERROR = "error"

    SERIAL_STATUS_CHOICES = [
        (SERIAL_STATUS_DISABLED, "Disabled"),
        (SERIAL_STATUS_DISCONNECTED, "Disconnected"),
        (SERIAL_STATUS_CONNECTED, "Connected"),
        (SERIAL_STATUS_ERROR, "Error"),
    ]

    connection_mode = models.CharField(
        max_length=32,
        choices=CONNECTION_MODE_CHOICES,
        default=CONNECTION_WIFI_ESP01,
    )
    linked_device = models.ForeignKey(
        "DWDDevice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="iot_configurations",
    )
    serial_enabled = models.BooleanField(default=False)
    serial_port = models.CharField(max_length=128, blank=True, default="COM3")
    baud_rate = models.PositiveIntegerField(default=9600)
    serial_status = models.CharField(
        max_length=32,
        choices=SERIAL_STATUS_CHOICES,
        default=SERIAL_STATUS_DISABLED,
    )
    serial_last_error = models.TextField(blank=True, default="")
    serial_last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "IoT configuration"
        verbose_name_plural = "IoT configuration"

    def __str__(self) -> str:
        return f"{self.connection_mode} serial={self.serial_status}"


class ProviderHealth(models.Model):
    STATUS_OK = "ok"
    STATUS_ERROR = "error"
    STATUS_DISABLED = "disabled"
    STATUS_NOT_CONFIGURED = "not_configured"

    STATUS_CHOICES = [
        (STATUS_OK, "OK"),
        (STATUS_ERROR, "Error"),
        (STATUS_DISABLED, "Disabled"),
        (STATUS_NOT_CONFIGURED, "Not configured"),
    ]

    name = models.CharField(max_length=64, unique=True)
    enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_NOT_CONFIGURED)

    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(null=True, blank=True)
    last_response_ms = models.FloatField(null=True, blank=True)
    response_count = models.PositiveIntegerField(default=0)
    total_response_ms = models.FloatField(default=0.0)

    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    win_count = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name}: {self.status}"


class RaceRun(models.Model):
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    request_id = models.CharField(max_length=64, db_index=True)
    started_at = models.DateTimeField(db_index=True)
    duration_ms = models.FloatField(null=True, blank=True)
    winner = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES)
    errors = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-created_at"]
        indexes = [
            models.Index(fields=["winner", "started_at"]),
            models.Index(fields=["status", "started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.request_id}: {self.winner or self.status}"


class SystemEvent(models.Model):
    LEVEL_DEBUG = "DEBUG"
    LEVEL_INFO = "INFO"
    LEVEL_WARNING = "WARNING"
    LEVEL_ERROR = "ERROR"

    LEVEL_CHOICES = [
        (LEVEL_DEBUG, "Debug"),
        (LEVEL_INFO, "Info"),
        (LEVEL_WARNING, "Warning"),
        (LEVEL_ERROR, "Error"),
    ]

    timestamp = models.DateTimeField(db_index=True)
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default=LEVEL_INFO, db_index=True)
    event = models.CharField(max_length=128, db_index=True)
    message = models.TextField(blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    source = models.CharField(max_length=64, blank=True, default="", db_index=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [
            models.Index(fields=["source", "timestamp"]),
            models.Index(fields=["event", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.timestamp.isoformat()} {self.level} {self.event}"


class DWDProviderApplication(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dwd_provider_applications",
    )
    city = models.CharField(max_length=128)
    email = models.EmailField(default="")
    country = models.CharField(max_length=128, blank=True, default="")
    region = models.CharField(max_length=128, blank=True, default="")
    address_comment = models.TextField(blank=True, default="")
    comment = models.TextField()
    admin_note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_dwd_provider_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["city", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.city} {self.status}"


class DWDDevice(models.Model):
    STATUS_INACTIVE = "inactive"
    STATUS_ACTIVE = "active"
    STATUS_BLOCKED = "blocked"

    STATUS_CHOICES = [
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_BLOCKED, "Blocked"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dwd_devices",
    )
    application = models.OneToOneField(
        DWDProviderApplication,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device",
    )
    device_code = models.CharField(max_length=64, unique=True, null=True, blank=True)
    station_id = models.CharField(max_length=64, unique=True)
    city = models.CharField(max_length=128)
    country = models.CharField(max_length=128, blank=True, default="")
    region = models.CharField(max_length=128, blank=True, default="")
    address_comment = models.TextField(blank=True, default="")
    firmware_type = models.CharField(max_length=32, blank=True, default="")
    firmware_version = models.CharField(max_length=64, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_request_at = models.DateTimeField(null=True, blank=True)
    last_data_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_INACTIVE, db_index=True)
    is_enabled = models.BooleanField(default=True)
    token = models.CharField(max_length=128, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    last_error_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["city", "status"]),
            models.Index(fields=["firmware_type", "status"]),
            models.Index(fields=["last_seen_at", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.station_id} {self.city} {self.status}"


class DWDProvisioning(models.Model):
    FIRMWARE_SERIAL_BRIDGE = "serial_bridge"
    FIRMWARE_ESP01_WIFI = "esp01_wifi"
    FIRMWARE_ETHERNET_SHIELD = "ethernet_shield"

    FIRMWARE_CHOICES = [
        (FIRMWARE_SERIAL_BRIDGE, "Serial bridge"),
        (FIRMWARE_ESP01_WIFI, "ESP-01 Wi-Fi"),
        (FIRMWARE_ETHERNET_SHIELD, "Ethernet shield"),
    ]

    DELIVERY_NOT_STARTED = "not_started"
    DELIVERY_FIRMWARE_ASSIGNED = "firmware_assigned"
    DELIVERY_INSTRUCTION_READY = "instruction_ready"
    DELIVERY_SENT = "sent"
    DELIVERY_ACKNOWLEDGED = "acknowledged"
    DELIVERY_PENDING = DELIVERY_NOT_STARTED

    DELIVERY_STATUS_CHOICES = [
        (DELIVERY_NOT_STARTED, "Not started"),
        (DELIVERY_FIRMWARE_ASSIGNED, "Firmware assigned"),
        (DELIVERY_INSTRUCTION_READY, "Instruction ready"),
        (DELIVERY_SENT, "Sent"),
        (DELIVERY_ACKNOWLEDGED, "Acknowledged"),
    ]

    CHANNEL_EMAIL = "email"
    CHANNEL_MANUAL = "manual"

    DELIVERY_CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, "Email"),
        (CHANNEL_MANUAL, "Manual"),
    ]

    application = models.ForeignKey(
        DWDProviderApplication,
        on_delete=models.CASCADE,
        related_name="provisioning_records",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dwd_provisioning_records",
    )
    device = models.ForeignKey(
        DWDDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provisioning_records",
    )
    firmware_type = models.CharField(max_length=32, choices=FIRMWARE_CHOICES)
    firmware_version = models.CharField(max_length=64, blank=True, default="")
    instruction_text = models.TextField()
    delivery_status = models.CharField(
        max_length=32,
        choices=DELIVERY_STATUS_CHOICES,
        default=DELIVERY_NOT_STARTED,
        db_index=True,
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_dwd_provisioning_records",
    )
    delivery_channel = models.CharField(max_length=32, choices=DELIVERY_CHANNEL_CHOICES, default=CHANNEL_MANUAL)
    notes = models.TextField(blank=True, default="")
    internal_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["firmware_type", "delivery_status"]),
            models.Index(fields=["user", "delivery_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.firmware_type} {self.delivery_status}"


class DWDDeviceEvent(models.Model):
    EVENT_REGISTERED = "registered"
    EVENT_ACTIVATED = "activated"
    EVENT_HEARTBEAT = "heartbeat"
    EVENT_DATA_INGEST = "data_ingest"
    EVENT_AUTH_FAILED = "auth_failed"
    EVENT_OFFLINE_DETECTED = "offline_detected"
    EVENT_BLOCKED = "blocked"
    EVENT_SETTINGS_CHANGED = "settings_changed"
    EVENT_ERROR = "error"

    EVENT_TYPE_CHOICES = [
        (EVENT_REGISTERED, "Registered"),
        (EVENT_ACTIVATED, "Activated"),
        (EVENT_HEARTBEAT, "Heartbeat"),
        (EVENT_DATA_INGEST, "Data ingest"),
        (EVENT_AUTH_FAILED, "Auth failed"),
        (EVENT_OFFLINE_DETECTED, "Offline detected"),
        (EVENT_BLOCKED, "Blocked"),
        (EVENT_SETTINGS_CHANGED, "Settings changed"),
        (EVENT_ERROR, "Error"),
    ]

    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_ERROR = "error"

    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_ERROR, "Error"),
    ]

    device = models.ForeignKey(DWDDevice, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=32, choices=EVENT_TYPE_CHOICES, db_index=True)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_INFO, db_index=True)
    message = models.TextField(blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["device", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["severity", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.device_id} {self.event_type} {self.severity}"
