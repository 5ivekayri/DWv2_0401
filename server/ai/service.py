from __future__ import annotations

import logging
from datetime import timezone as dt_timezone

from django.utils import timezone

from server.ai.openrouter_client import OpenRouterClient
from server.ai.prompts import (
    PROMPT_VERSION,
    build_system_prompt,
    build_user_prompt,
)
from server.ai.quality import (
    build_fallback_recommendation,
    clean_recommendation_text,
    is_recommendation_consistent_with_weather,
    is_recommendation_usable,
)
from server.models import AIOutfitRecommendation


ai_log = logging.getLogger("server.api")


class OutfitRecommendationService:
    def __init__(self) -> None:
        self.client = OpenRouterClient()

    @staticmethod
    def get_hour_bucket():
        now = timezone.now().astimezone(dt_timezone.utc)
        return now.replace(minute=0, second=0, microsecond=0)

    def _normalize_recommendation(
        self,
        text: str,
        *,
        city: str,
        temperature_c: float,
        humidity: float,
        wind_speed_ms: float,
        precipitation_mm: float,
        condition: str = "",
        model_name: str = "",
    ) -> tuple[str, bool]:
        cleaned = clean_recommendation_text(text)
        if is_recommendation_usable(cleaned) and is_recommendation_consistent_with_weather(
            cleaned,
            temperature_c=temperature_c,
            precipitation_mm=precipitation_mm,
            condition=condition,
        ):
            return cleaned, False

        fallback = build_fallback_recommendation(
            city=city,
            temperature_c=temperature_c,
            humidity=humidity,
            wind_speed_ms=wind_speed_ms,
            precipitation_mm=precipitation_mm,
            condition=condition,
        )
        ai_log.warning(
            "ai_outfit_quality_fallback city=%s model=%s raw_preview=%s",
            city,
            model_name or self.client.model_name,
            str(text)[:120],
        )
        return fallback, True

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
            normalized, _ = self._normalize_recommendation(
                existing.recommendation_text,
                city=existing.city,
                temperature_c=existing.temperature_c,
                humidity=existing.humidity,
                wind_speed_ms=existing.wind_speed_ms,
                precipitation_mm=existing.precipitation_mm,
                condition=existing.condition,
                model_name=existing.model_name,
            )
            if normalized != existing.recommendation_text:
                existing.recommendation_text = normalized
                existing.save(update_fields=["recommendation_text"])
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
        recommendation_text, _ = self._normalize_recommendation(
            recommendation_text,
            city=city,
            temperature_c=temperature_c,
            humidity=humidity,
            wind_speed_ms=wind_speed_ms,
            precipitation_mm=precipitation_mm,
            condition=condition,
            model_name=model_name,
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

    def regenerate_recommendation(self, obj: AIOutfitRecommendation) -> AIOutfitRecommendation:
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(
            city=obj.city,
            temperature_c=obj.temperature_c,
            humidity=obj.humidity,
            wind_speed_ms=obj.wind_speed_ms,
            precipitation_mm=obj.precipitation_mm,
            condition=obj.condition,
        )
        recommendation_text, model_name = self.client.create_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        recommendation_text, _ = self._normalize_recommendation(
            recommendation_text,
            city=obj.city,
            temperature_c=obj.temperature_c,
            humidity=obj.humidity,
            wind_speed_ms=obj.wind_speed_ms,
            precipitation_mm=obj.precipitation_mm,
            condition=obj.condition,
            model_name=model_name,
        )
        obj.recommendation_text = recommendation_text
        obj.model_name = model_name
        obj.prompt_version = PROMPT_VERSION
        obj.save(update_fields=["recommendation_text", "model_name", "prompt_version"])
        return obj
