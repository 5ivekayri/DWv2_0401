from __future__ import annotations

import logging
import requests
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from server.ai.service import OutfitRecommendationService
from .weather.contracts import WeatherPoint
from .weather.factory import build_weather_service

log = logging.getLogger("weather.race")
_service = build_weather_service()


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    return Response({"status": "ok"})


class WeatherView(APIView):
    permission_classes = [AllowAny]

    def _run_provider(self, provider, lat: float, lon: float, request_id: str):
        provider_name = getattr(provider, "name", provider.__class__.__name__)
        started = time.perf_counter()

        log.info(
            "provider_started request_id=%s provider=%s",
            request_id,
            provider_name,
        )

        try:
            point = provider.get_weather(lat, lon)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)

            log.info(
                "provider_succeeded request_id=%s provider=%s duration_ms=%s",
                request_id,
                provider_name,
                duration_ms,
            )

            return {
                "provider": provider_name,
                "success": True,
                "duration_ms": duration_ms,
                "point": point,
                "error": None,
            }

        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)

            log.warning(
                "provider_failed request_id=%s provider=%s duration_ms=%s error_type=%s error=%s",
                request_id,
                provider_name,
                duration_ms,
                type(exc).__name__,
                str(exc),
            )

            return {
                "provider": provider_name,
                "success": False,
                "duration_ms": duration_ms,
                "point": None,
                "error": exc,
            }

    def get(self, request):
        city = request.query_params.get("city")

        if city == "test":
            point = WeatherPoint(
                latitude=0.0,
                longitude=0.0,
                temperature_c=0.0,
                pressure_hpa=0.0,
                wind_speed_ms=0.0,
                precipitation_mm=0.0,
                observed_at=datetime.now(timezone.utc),
                source="stub",
            )
            payload = asdict(point)
            payload["observed_at"] = point.observed_at.isoformat().replace("+00:00", "Z")
            return Response(payload, status=200)

        try:
            lat = float(request.query_params["lat"])
            lon = float(request.query_params["lon"])
        except KeyError:
            return Response(
                {"detail": "lat and lon query parameters are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError:
            return Response(
                {"detail": "lat and lon must be valid floating point numbers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]

        providers = getattr(_service, "providers", None)
        if not providers:
            log.error("no_providers_configured request_id=%s", request_id)
            return Response(
                {"detail": "no providers configured", "request_id": request_id},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        log.info(
            "all_providers request_id=%s providers=%s",
            request_id,
            [getattr(p, "name", p.__class__.__name__) for p in providers],
        )

        enabled = []
        for provider in providers:
            provider_name = getattr(provider, "name", provider.__class__.__name__)

            try:
                is_enabled = getattr(provider, "is_enabled", lambda: True)()
            except Exception as exc:
                log.warning(
                    "provider_enabled_check_failed request_id=%s provider=%s error_type=%s error=%s",
                    request_id,
                    provider_name,
                    type(exc).__name__,
                    str(exc),
                )
                is_enabled = False

            log.info(
                "provider_status request_id=%s provider=%s enabled=%s",
                request_id,
                provider_name,
                is_enabled,
            )

            if is_enabled:
                enabled.append(provider)

        if not enabled:
            log.error("no_enabled_providers request_id=%s", request_id)
            return Response(
                {"detail": "no enabled providers (missing API keys?)", "request_id": request_id},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        log.info(
            "race_started request_id=%s providers=%s lat=%s lon=%s",
            request_id,
            [getattr(p, "name", p.__class__.__name__) for p in enabled],
            lat,
            lon,
        )

        race_started = time.perf_counter()
        max_workers = min(len(enabled), 4)
        results = []
        last_exc = None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._run_provider, provider, lat, lon, request_id): provider
                for provider in enabled
            }

            for future in as_completed(futures):
                result = future.result()
                results.append(result)

                if result["success"]:
                    total_race_ms = round((time.perf_counter() - race_started) * 1000, 2)
                    point = result["point"]

                    log.info(
                        "race_winner_selected request_id=%s winner=%s winner_duration_ms=%s total_race_ms=%s",
                        request_id,
                        result["provider"],
                        result["duration_ms"],
                        total_race_ms,
                    )

                    payload = asdict(point)
                    payload["observed_at"] = (
                        point.observed_at.astimezone(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
                    payload["request_id"] = request_id

                    return Response(payload, status=status.HTTP_200_OK)

                last_exc = result["error"]

        total_race_ms = round((time.perf_counter() - race_started) * 1000, 2)

        log.error(
            "race_failed request_id=%s total_race_ms=%s tried=%s last_error=%s",
            request_id,
            total_race_ms,
            [r["provider"] for r in results],
            str(last_exc),
        )

        return Response(
            {
                "detail": f"all providers failed: {last_exc}",
                "request_id": request_id,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


class AIOutfitRecommendationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            city = str(request.data["city"]).strip()
            temperature_c = float(request.data["temperature_c"])
            humidity = float(request.data["humidity"])
            wind_speed_ms = float(request.data["wind_speed_ms"])
            precipitation_mm = float(request.data["precipitation_mm"])
            condition = str(request.data.get("condition", "")).strip()
        except KeyError as exc:
            return Response(
                {"detail": f"missing required field: {exc.args[0]}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (TypeError, ValueError):
            return Response(
                {"detail": "invalid request payload"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not city:
            return Response(
                {"detail": "city must not be empty"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = OutfitRecommendationService()

        if not service.client.is_enabled():
            return Response(
                {"detail": "AI service is not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            obj, created = service.get_or_create_recommendation(
                city=city,
                temperature_c=temperature_c,
                humidity=humidity,
                wind_speed_ms=wind_speed_ms,
                precipitation_mm=precipitation_mm,
                condition=condition,
            )
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 502
            return Response(
                {"detail": f"OpenRouter HTTP error: {status_code}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            return Response(
                {"detail": f"AI recommendation service unavailable: {type(exc).__name__}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "city": obj.city,
                "hour_bucket": obj.hour_bucket.isoformat().replace("+00:00", "Z"),
                "recommendation": obj.recommendation_text,
                "model": obj.model_name,
                "source": "db" if not created else "openrouter",
            },
            status=status.HTTP_200_OK,
        )