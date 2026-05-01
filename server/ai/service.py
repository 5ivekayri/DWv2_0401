from __future__ import annotations

from datetime import timezone as dt_timezone

from django.utils import timezone

from server.ai.openrouter_client import OpenRouterClient
from server.ai.prompts import (
    PROMPT_VERSION,
    build_system_prompt,
    build_user_prompt,
)
from server.models import AIOutfitRecommendation


class OutfitRecommendationService:
    def __init__(self) -> None:
        self.client = OpenRouterClient()

    @staticmethod
    def get_hour_bucket():
        now = timezone.now().astimezone(dt_timezone.utc)
        return now.replace(minute=0, second=0, microsecond=0)

    def get_or_create_recommendation(
        self,
        *,
        city: str,
        temperature_c: float,
        humidity: float,
        wind_speed_ms: float,
        precipitation_mm: float,
        condition: str = "",
    ):
        hour_bucket = self.get_hour_bucket()

        existing = (
            AIOutfitRecommendation.objects
            .filter(city=city, hour_bucket=hour_bucket, prompt_version=PROMPT_VERSION)
            .order_by("-created_at")
            .first()
        )
        if existing:
            return existing, False

        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(
            city=city,
            temperature_c=temperature_c,
            humidity=humidity,
            wind_speed_ms=wind_speed_ms,
            precipitation_mm=precipitation_mm,
            condition=condition,
        )

        recommendation_text, model_name = self.client.create_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        obj = AIOutfitRecommendation.objects.create(
            city=city,
            hour_bucket=hour_bucket,
            temperature_c=temperature_c,
            humidity=humidity,
            wind_speed_ms=wind_speed_ms,
            precipitation_mm=precipitation_mm,
            condition=condition or "",
            model_name=model_name,
            prompt_version=PROMPT_VERSION,
            recommendation_text=recommendation_text,
        )
        return obj, True
