from __future__ import annotations

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
