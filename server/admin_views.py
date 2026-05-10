from __future__ import annotations

import os
import socket
import time
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema, inline_serializer

from server.ai.service import OutfitRecommendationService
from server.models import ProviderHealth, RaceRun, SystemEvent
from server.monitoring import (
    KNOWN_PROVIDERS,
    ensure_provider_health,
    get_latest_station_status,
    provider_health_to_payload,
    race_run_to_payload,
    record_provider_failure,
    record_provider_success,
    record_system_event,
    system_event_to_payload,
    utc_iso,
)
from server.weather.factory import build_weather_service


ERROR_RESPONSE = inline_serializer(
    name="AdminErrorResponse",
    fields={"detail": serializers.CharField()},
)

PROVIDER_CHECK_REQUEST = inline_serializer(
    name="AdminProviderCheckRequest",
    fields={
        "provider": serializers.CharField(),
        "lat": serializers.FloatField(),
        "lon": serializers.FloatField(),
    },
)

PROVIDER_CHECK_RESPONSE = inline_serializer(
    name="AdminProviderCheckResponse",
    fields={
        "provider": serializers.CharField(),
        "status": serializers.CharField(),
        "response_ms": serializers.FloatField(required=False, allow_null=True),
        "sample": serializers.DictField(required=False, allow_null=True),
        "error": serializers.CharField(required=False, allow_null=True),
    },
)


def documented_responses(success_schema: Any | None = None) -> dict[int, Any]:
    responses: dict[int, Any] = {
        400: ERROR_RESPONSE,
        401: OpenApiResponse(description="Authentication credentials were not provided."),
        403: OpenApiResponse(description="Authenticated user is not an administrator."),
        500: ERROR_RESPONSE,
    }
    responses[200] = success_schema or OpenApiResponse(description="OK")
    return responses


def get_provider_map():
    providers = {provider.name: provider for provider in build_weather_service().providers}
    return {name: providers.get(name) for name in KNOWN_PROVIDERS}


def provider_configuration(provider_name: str, provider) -> tuple[bool, str, str | None]:
    if provider_name == "yandex":
        if os.getenv("YANDEX_WEATHER_API_KEY", "").strip():
            return False, ProviderHealth.STATUS_DISABLED, "Provider is not implemented"
        return False, ProviderHealth.STATUS_NOT_CONFIGURED, "API key is not configured"

    if provider is None:
        return False, ProviderHealth.STATUS_DISABLED, "Provider is not implemented"

    try:
        enabled = bool(provider.is_enabled())
    except Exception as exc:
        return False, ProviderHealth.STATUS_ERROR, str(exc)

    if not enabled:
        return False, ProviderHealth.STATUS_NOT_CONFIGURED, "API key is not configured"
    return True, ProviderHealth.STATUS_OK, None


def sync_provider_health() -> list[ProviderHealth]:
    provider_map = get_provider_map()
    result = []

    for provider_name, provider in provider_map.items():
        enabled, configured_status, message = provider_configuration(provider_name, provider)
        obj = ensure_provider_health(provider_name, enabled=enabled)
        if obj is None:
            continue

        previous_enabled = obj.enabled
        previous_status = obj.status
        obj.enabled = enabled
        if not enabled:
            obj.status = configured_status
            obj.last_error_message = message
        elif obj.status in {ProviderHealth.STATUS_NOT_CONFIGURED, ProviderHealth.STATUS_DISABLED}:
            obj.status = ProviderHealth.STATUS_OK
            obj.last_error_message = None
        obj.save(update_fields=["enabled", "status", "last_error_message", "updated_at"])
        if previous_enabled != obj.enabled or previous_status != obj.status:
            record_system_event(
                event="admin_config_changed",
                source="admin",
                message=f"Provider {provider_name} monitoring status changed",
                payload={
                    "provider": provider_name,
                    "enabled": obj.enabled,
                    "status": obj.status,
                    "previous_enabled": previous_enabled,
                    "previous_status": previous_status,
                },
            )
        result.append(obj)

    return result


def check_database() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return "ok"
    except Exception:
        return "error"


def check_redis() -> str:
    try:
        cache.set("admin_health_probe", "ok", timeout=5)
        return "ok" if cache.get("admin_health_probe") == "ok" else "error"
    except Exception:
        return "error"


def check_mqtt() -> str:
    host = getattr(settings, "MQTT_HOST", "127.0.0.1")
    port = int(getattr(settings, "MQTT_PORT", 1883))
    try:
        with socket.create_connection((host, port), timeout=1):
            return "ok"
    except OSError as exc:
        record_system_event(
            event="mqtt_connection_failed",
            source="iot",
            level=SystemEvent.LEVEL_WARNING,
            message=str(exc),
            payload={"host": host, "port": port},
        )
        return "error"


def check_ai() -> str:
    try:
        return "ok" if OutfitRecommendationService().client.is_enabled() else "not_configured"
    except Exception:
        return "error"


def avg_response_ms(provider: ProviderHealth) -> float | None:
    if provider.response_count <= 0:
        return None
    return round(provider.total_response_ms / provider.response_count, 2)


class AdminDashboardView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only summary of backend components, providers and IoT station status.",
        responses=documented_responses(),
    )
    def get(self, request):
        record_system_event(
            event="admin_dashboard_opened",
            source="admin",
            message=f"Admin user {request.user.pk} opened dashboard",
            payload={"user_id": request.user.pk},
        )

        providers = {
            payload["name"]: payload["status"]
            for payload in (provider_health_to_payload(obj) for obj in sync_provider_health())
        }
        station = get_latest_station_status(
            offline_after_seconds=getattr(settings, "IOT_OFFLINE_AFTER_SECONDS", 3600)
        )

        return Response(
            {
                "status": "ok",
                "components": {
                    "database": check_database(),
                    "redis": check_redis(),
                    "mqtt": check_mqtt(),
                    "ai": check_ai(),
                },
                "providers": providers,
                "iot_station": {
                    "status": station["status"],
                    "last_seen": station["last_seen"],
                },
            },
            status=status.HTTP_200_OK,
        )


class AdminProvidersStatusView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only status and counters for all weather providers.",
        responses=documented_responses(),
    )
    def get(self, _request):
        providers = [provider_health_to_payload(obj) for obj in sync_provider_health()]
        return Response(providers, status=status.HTTP_200_OK)


class AdminProviderCheckView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only manual check of a specific weather provider.",
        request=PROVIDER_CHECK_REQUEST,
        responses=documented_responses(PROVIDER_CHECK_RESPONSE),
    )
    def post(self, request):
        try:
            provider_name = str(request.data["provider"]).strip().lower()
            lat = float(request.data["lat"])
            lon = float(request.data["lon"])
        except KeyError as exc:
            return Response(
                {"detail": f"missing required field: {exc.args[0]}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (TypeError, ValueError):
            return Response({"detail": "invalid request payload"}, status=status.HTTP_400_BAD_REQUEST)

        record_system_event(
            event="admin_provider_check_requested",
            source="admin",
            message=f"Provider {provider_name} manual check requested",
            payload={"provider": provider_name, "lat": lat, "lon": lon, "user_id": request.user.pk},
        )

        provider = get_provider_map().get(provider_name)
        if provider_name not in KNOWN_PROVIDERS:
            return Response({"detail": "unknown provider"}, status=status.HTTP_400_BAD_REQUEST)

        enabled, configured_status, message = provider_configuration(provider_name, provider)
        if not enabled:
            obj = ensure_provider_health(provider_name, enabled=False)
            if obj is not None:
                obj.status = configured_status
                obj.last_error_message = message
                obj.save(update_fields=["status", "last_error_message", "updated_at"])
            return Response(
                {
                    "provider": provider_name,
                    "status": configured_status,
                    "response_ms": None,
                    "sample": None,
                    "error": message,
                },
                status=status.HTTP_200_OK,
            )

        started = time.perf_counter()
        try:
            point = provider.get_weather(lat, lon)
        except Exception as exc:
            response_ms = round((time.perf_counter() - started) * 1000, 2)
            record_provider_failure(name=provider_name, duration_ms=response_ms, error_message=str(exc))
            return Response(
                {
                    "provider": provider_name,
                    "status": ProviderHealth.STATUS_ERROR,
                    "response_ms": response_ms,
                    "sample": None,
                    "error": str(exc),
                },
                status=status.HTTP_200_OK,
            )

        response_ms = round((time.perf_counter() - started) * 1000, 2)
        record_provider_success(name=provider_name, duration_ms=response_ms)
        return Response(
            {
                "provider": provider_name,
                "status": ProviderHealth.STATUS_OK,
                "response_ms": response_ms,
                "sample": {
                    "temperature": point.temperature_c,
                    "humidity": None,
                    "wind_speed": point.wind_speed_ms,
                },
            },
            status=status.HTTP_200_OK,
        )


class AdminRaceStatsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only Race / First Complete statistics.",
        responses=documented_responses(),
    )
    def get(self, _request):
        providers = []
        for obj in sync_provider_health():
            providers.append(
                {
                    "name": obj.name,
                    "avg_response_ms": avg_response_ms(obj),
                    "win_count": obj.win_count,
                    "success_count": obj.success_count,
                    "error_count": obj.error_count,
                }
            )

        recent = list(RaceRun.objects.order_by("-started_at", "-created_at")[:20])
        last = recent[0] if recent else None

        return Response(
            {
                "strategy": "first_complete",
                "last_winner": last.winner if last else None,
                "last_request_id": last.request_id if last else None,
                "providers": providers,
                "recent_races": [race_run_to_payload(obj) for obj in recent],
            },
            status=status.HTTP_200_OK,
        )


class AdminIotStatusView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only Arduino / IoT station and MQTT status.",
        responses=documented_responses(),
    )
    def get(self, _request):
        station = get_latest_station_status(
            offline_after_seconds=getattr(settings, "IOT_OFFLINE_AFTER_SECONDS", 3600)
        )
        return Response(
            {
                "station_name": getattr(settings, "IOT_STATION_NAME", "Arduino Uno Weather Station"),
                "fixed_city": getattr(settings, "IOT_FIXED_CITY", "Saransk"),
                "status": station["status"],
                "last_seen": station["last_seen"],
                "last_reading": station["last_reading"],
                "mqtt": {
                    "broker": getattr(settings, "MQTT_BROKER_NAME", "mosquitto"),
                    "status": check_mqtt(),
                    "topic": getattr(settings, "MQTT_TOPIC", "weather/station"),
                },
            },
            status=status.HTTP_200_OK,
        )


class AdminLogsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only latest structured system events.",
        parameters=[
            OpenApiParameter("level", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses=documented_responses(),
    )
    def get(self, request):
        level = str(request.query_params.get("level", "")).strip().upper()
        if level and level not in dict(SystemEvent.LEVEL_CHOICES):
            return Response({"detail": "invalid level"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 500)
        except ValueError:
            return Response({"detail": "limit must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        events = SystemEvent.objects.all()
        if level:
            events = events.filter(level=level)

        return Response(
            [system_event_to_payload(obj) for obj in events.order_by("-timestamp", "-id")[:limit]],
            status=status.HTTP_200_OK,
        )
