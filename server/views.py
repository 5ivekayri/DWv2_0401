from __future__ import annotations

import logging
import requests
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone

from django.conf import settings
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema, inline_serializer

from server.ai.service import OutfitRecommendationService
from server.models import WeatherHourlySnapshot, WeatherStationReading
from .weather.contracts import WeatherPoint
from .weather.factory import build_weather_service
from .weather.geocoding import geocode_city
from .weather.storage import (
    get_cached_weather_payload,
    get_hour_bucket,
    get_stored_weather_payload,
    normalize_coordinate,
    snapshot_to_payload,
    station_reading_to_payload,
    store_station_reading_snapshot,
    store_weather_point,
)

log = logging.getLogger("weather.race")
api_log = logging.getLogger("server.api")
_service = build_weather_service()


AI_OUTFIT_REQUEST_SCHEMA = inline_serializer(
    name="AIOutfitRecommendationRequest",
    fields={
        "city": serializers.CharField(),
        "temperature_c": serializers.FloatField(),
        "humidity": serializers.FloatField(),
        "wind_speed_ms": serializers.FloatField(),
        "precipitation_mm": serializers.FloatField(),
        "condition": serializers.CharField(required=False, allow_blank=True),
    },
)

AI_OUTFIT_RESPONSE_SCHEMA = inline_serializer(
    name="AIOutfitRecommendationResponse",
    fields={
        "city": serializers.CharField(),
        "hour_bucket": serializers.CharField(),
        "recommendation": serializers.CharField(),
        "model": serializers.CharField(),
        "source": serializers.CharField(),
    },
)

STATION_READING_REQUEST_SCHEMA = inline_serializer(
    name="StationReadingRequest",
    fields={
        "station_id": serializers.CharField(required=False),
        "latitude": serializers.FloatField(required=False),
        "longitude": serializers.FloatField(required=False),
        "temperature_c": serializers.FloatField(),
        "humidity": serializers.FloatField(required=False),
        "pressure_hpa": serializers.FloatField(required=False),
        "wind_speed_ms": serializers.FloatField(required=False),
        "precipitation_mm": serializers.FloatField(required=False),
        "observed_at": serializers.CharField(required=False),
    },
)


@extend_schema(responses={200: OpenApiResponse(description="Service health status")})
@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    return Response({"status": "ok"})


class GeocodeView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("city", OpenApiTypes.STR, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("language", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiResponse(description="Geocoding results")},
    )
    def get(self, request):
        city = str(request.query_params.get("city") or request.query_params.get("q") or "").strip()
        if not city:
            api_log.warning("geocode_rejected reason=missing_city")
            return Response(
                {"detail": "city query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            limit = min(max(int(request.query_params.get("limit", 5)), 1), 10)
        except ValueError:
            api_log.warning("geocode_rejected city=%s reason=bad_limit", city)
            return Response(
                {"detail": "limit must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        language = str(request.query_params.get("language", "ru")).strip() or "ru"
        started = time.perf_counter()
        api_log.info("geocode_started city=%s limit=%s language=%s", city, limit, language)

        try:
            results = geocode_city(city=city, limit=limit, language=language)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 502
            api_log.warning("geocode_failed city=%s error_type=http status=%s", city, status_code)
            return Response(
                {"detail": f"geocoding provider HTTP error: {status_code}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except requests.RequestException:
            api_log.warning("geocode_failed city=%s error_type=request_exception", city)
            return Response(
                {"detail": "geocoding provider unavailable"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not results:
            api_log.info("geocode_not_found city=%s duration_ms=%s", city, round((time.perf_counter() - started) * 1000, 2))
            return Response(
                {"detail": "city not found", "query": city, "results": []},
                status=status.HTTP_404_NOT_FOUND,
            )

        api_log.info(
            "geocode_succeeded city=%s results=%s duration_ms=%s",
            city,
            len(results),
            round((time.perf_counter() - started) * 1000, 2),
        )
        return Response({"query": city, "results": results}, status=status.HTTP_200_OK)


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

    @extend_schema(
        parameters=[
            OpenApiParameter("lat", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("lon", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("city", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiResponse(description="Current weather payload")},
    )
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
        hour_bucket = get_hour_bucket()
        api_log.info("weather_request_started request_id=%s lat=%s lon=%s city=%s", request_id, lat, lon, city or "")

        cached_payload = get_cached_weather_payload(
            latitude=lat,
            longitude=lon,
            hour_bucket=hour_bucket,
        )
        if cached_payload:
            payload = dict(cached_payload)
            payload["request_id"] = request_id
            payload["cache_status"] = "redis_hit"
            log.info(
                "weather_cache_hit request_id=%s layer=redis lat=%s lon=%s hour_bucket=%s",
                request_id,
                lat,
                lon,
                hour_bucket.isoformat(),
            )
            api_log.info("weather_response_ready request_id=%s status=200 cache_status=redis_hit source=%s", request_id, payload.get("source"))
            return Response(payload, status=status.HTTP_200_OK)

        stored_payload = get_stored_weather_payload(
            latitude=lat,
            longitude=lon,
            hour_bucket=hour_bucket,
        )
        if stored_payload:
            payload = dict(stored_payload)
            payload["request_id"] = request_id
            payload["cache_status"] = "mysql_hit"
            log.info(
                "weather_cache_hit request_id=%s layer=mysql lat=%s lon=%s hour_bucket=%s",
                request_id,
                lat,
                lon,
                hour_bucket.isoformat(),
            )
            api_log.info("weather_response_ready request_id=%s status=200 cache_status=mysql_hit source=%s", request_id, payload.get("source"))
            return Response(payload, status=status.HTTP_200_OK)

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

                    payload = store_weather_point(
                        point=point,
                        city=city,
                        hour_bucket=hour_bucket,
                        latitude=lat,
                        longitude=lon,
                    )
                    payload["request_id"] = request_id
                    payload["cache_status"] = "miss_stored"

                    api_log.info("weather_response_ready request_id=%s status=200 cache_status=miss_stored source=%s", request_id, payload.get("source"))
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

    @extend_schema(
        request=AI_OUTFIT_REQUEST_SCHEMA,
        responses={200: AI_OUTFIT_RESPONSE_SCHEMA},
    )
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
            api_log.warning("ai_outfit_rejected reason=empty_city")
            return Response(
                {"detail": "city must not be empty"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = OutfitRecommendationService()
        api_log.info(
            "ai_outfit_started city=%s temperature_c=%s wind_speed_ms=%s precipitation_mm=%s",
            city,
            temperature_c,
            wind_speed_ms,
            precipitation_mm,
        )

        if not service.client.is_enabled():
            api_log.warning("ai_outfit_unavailable city=%s reason=not_configured", city)
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
            api_log.warning("ai_outfit_failed city=%s error_type=http status=%s", city, status_code)
            return Response(
                {"detail": f"OpenRouter HTTP error: {status_code}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            api_log.warning("ai_outfit_failed city=%s error_type=%s", city, type(exc).__name__)
            return Response(
                {"detail": f"AI recommendation service unavailable: {type(exc).__name__}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        api_log.info("ai_outfit_succeeded city=%s source=%s", city, "openrouter" if created else "db")
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


class WeatherHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("lat", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("lon", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiResponse(description="Hourly weather history")},
    )
    def get(self, request):
        try:
            lat = normalize_coordinate(float(request.query_params["lat"]))
            lon = normalize_coordinate(float(request.query_params["lon"]))
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

        try:
            limit = min(max(int(request.query_params.get("limit", 24)), 1), 168)
        except ValueError:
            return Response(
                {"detail": "limit must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        snapshots = (
            WeatherHourlySnapshot.objects
            .filter(
                latitude=lat,
                longitude=lon,
                data_source=WeatherHourlySnapshot.SOURCE_EXTERNAL_API,
            )
            .order_by("-hour_bucket")[:limit]
        )

        data = []
        for snapshot in reversed(list(snapshots)):
            payload = snapshot_to_payload(snapshot)
            payload["hour_bucket"] = snapshot.hour_bucket.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            payload["data_source"] = snapshot.data_source
            data.append(payload)

        api_log.info(
            "weather_history_succeeded user_id=%s lat=%s lon=%s limit=%s results=%s",
            request.user.pk,
            lat,
            lon,
            limit,
            len(data),
        )
        return Response({"results": data}, status=status.HTTP_200_OK)


class StationReadingIngestView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        request=STATION_READING_REQUEST_SCHEMA,
        responses={201: OpenApiResponse(description="Created station reading")},
    )
    def post(self, request):
        configured_key = getattr(settings, "STATION_API_KEY", "")
        if configured_key and request.headers.get("X-Station-Key") != configured_key:
            api_log.warning("station_ingest_rejected reason=invalid_key")
            return Response({"detail": "invalid station key"}, status=status.HTTP_403_FORBIDDEN)

        try:
            station_id = str(request.data.get("station_id", "arduino-1")).strip() or "arduino-1"
            temperature_c = float(request.data["temperature_c"])
            humidity = self._optional_float(request.data.get("humidity"))
            pressure_hpa = self._optional_float(request.data.get("pressure_hpa"))
            wind_speed_ms = float(request.data.get("wind_speed_ms", 0.0))
            precipitation_mm = float(request.data.get("precipitation_mm", 0.0))
            latitude = self._optional_float(request.data.get("latitude"))
            longitude = self._optional_float(request.data.get("longitude"))
            observed_at = self._parse_observed_at(request.data.get("observed_at"))
        except KeyError as exc:
            return Response(
                {"detail": f"missing required field: {exc.args[0]}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (TypeError, ValueError):
            return Response(
                {"detail": "invalid station payload"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reading = WeatherStationReading.objects.create(
            station_id=station_id,
            latitude=latitude,
            longitude=longitude,
            temperature_c=temperature_c,
            humidity=humidity,
            pressure_hpa=pressure_hpa,
            wind_speed_ms=wind_speed_ms,
            precipitation_mm=precipitation_mm,
            observed_at=observed_at,
            raw_payload=dict(request.data),
        )
        store_station_reading_snapshot(reading)

        api_log.info("station_ingest_succeeded station_id=%s reading_id=%s", reading.station_id, reading.pk)
        return Response(station_reading_to_payload(reading), status=status.HTTP_201_CREATED)

    @staticmethod
    def _optional_float(value):
        if value in (None, ""):
            return None
        return float(value)

    @staticmethod
    def _parse_observed_at(value):
        if not value:
            return django_timezone.now()
        parsed = parse_datetime(str(value))
        if parsed is None:
            raise ValueError("invalid observed_at")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed


class StationLatestView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("station_id", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False)],
        responses={200: OpenApiResponse(description="Latest station reading")},
    )
    def get(self, request):
        station_id = request.query_params.get("station_id", "arduino-1")
        reading = (
            WeatherStationReading.objects
            .filter(station_id=station_id)
            .order_by("-observed_at", "-created_at")
            .first()
        )
        if not reading:
            api_log.info("station_latest_not_found station_id=%s", station_id)
            return Response({"detail": "station reading not found"}, status=status.HTTP_404_NOT_FOUND)
        api_log.info("station_latest_succeeded station_id=%s reading_id=%s", station_id, reading.pk)
        return Response(station_reading_to_payload(reading), status=status.HTTP_200_OK)


class StationHistoryView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("station_id", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiResponse(description="Station readings history")},
    )
    def get(self, request):
        station_id = request.query_params.get("station_id", "arduino-1")
        try:
            limit = min(max(int(request.query_params.get("limit", 100)), 1), 1000)
        except ValueError:
            return Response(
                {"detail": "limit must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        readings = (
            WeatherStationReading.objects
            .filter(station_id=station_id)
            .order_by("-observed_at", "-created_at")[:limit]
        )
        data = [station_reading_to_payload(reading) for reading in reversed(list(readings))]
        api_log.info("station_history_succeeded station_id=%s limit=%s results=%s", station_id, limit, len(data))
        return Response(
            {"results": data},
            status=status.HTTP_200_OK,
        )
