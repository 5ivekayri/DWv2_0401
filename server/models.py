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