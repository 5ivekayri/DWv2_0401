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
from server.iot.config import get_iot_config, serialize_iot_config
from server.models import DWDDevice, IoTConfiguration, ProviderHealth, RaceRun, SystemEvent
from server.monitoring import (
    KNOWN_PROVIDERS,
    KNOWN_RACE_PROVIDERS,
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
from server.weather.visual_crossing import VisualCrossingClient, normalize_visual_crossing_payload


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

class AdminIotConfigSerializer(serializers.Serializer):
    connection_mode = serializers.ChoiceField(
        choices=[choice[0] for choice in IoTConfiguration.CONNECTION_MODE_CHOICES],
        required=False,
    )
    serial_port = serializers.CharField(required=False, allow_blank=True)
    baud_rate = serializers.IntegerField(required=False, min_value=1200, max_value=1000000)
    linked_device_id = serializers.IntegerField(required=False, allow_null=True)
    enabled = serializers.BooleanField(required=False)


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
    return {name: providers.get(name) for name in KNOWN_RACE_PROVIDERS}


def provider_configuration(provider_name: str, provider) -> tuple[bool, str, str | None]:
    if provider_name == "visual_crossing":
        if getattr(settings, "VISUAL_CROSSING_API_KEY", ""):
            return True, ProviderHealth.STATUS_OK, None
        return False, ProviderHealth.STATUS_NOT_CONFIGURED, "API key is not configured"

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

    for provider_name in KNOWN_PROVIDERS:
        provider = provider_map.get(provider_name)
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

        if provider_name not in KNOWN_PROVIDERS:
            return Response({"detail": "unknown provider"}, status=status.HTTP_400_BAD_REQUEST)

        provider = get_provider_map().get(provider_name)
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

        if provider_name == "visual_crossing":
            return self._check_visual_crossing(lat=lat, lon=lon)

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

    def _check_visual_crossing(self, *, lat: float, lon: float) -> Response:
        started = time.perf_counter()
        try:
            raw_payload = VisualCrossingClient().fetch_forecast(latitude=lat, longitude=lon, days=1)
            daily, _hourly, _resolved = normalize_visual_crossing_payload(
                raw_payload,
                city="",
                latitude=lat,
                longitude=lon,
                days=1,
            )
        except Exception as exc:
            response_ms = round((time.perf_counter() - started) * 1000, 2)
            record_provider_failure(name="visual_crossing", duration_ms=response_ms, error_message=str(exc))
            return Response(
                {
                    "provider": "visual_crossing",
                    "status": ProviderHealth.STATUS_ERROR,
                    "response_ms": response_ms,
                    "sample": None,
                    "error": str(exc),
                },
                status=status.HTTP_200_OK,
            )

        response_ms = round((time.perf_counter() - started) * 1000, 2)
        record_provider_success(name="visual_crossing", duration_ms=response_ms)
        first_day = daily[0] if daily else {}
        return Response(
            {
                "provider": "visual_crossing",
                "status": ProviderHealth.STATUS_OK,
                "response_ms": response_ms,
                "sample": {
                    "temperature": first_day.get("temp_max"),
                    "humidity": first_day.get("humidity"),
                    "wind_speed": first_day.get("wind_speed"),
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
            if obj.name not in KNOWN_RACE_PROVIDERS:
                continue
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
        description="Admin-only Arduino / IoT station, MQTT and Serial Bridge status.",
        responses=documented_responses(),
    )
    def get(self, _request):
        config = get_iot_config()
        config_payload = serialize_iot_config(config)
        station = get_latest_station_status(
            offline_after_seconds=getattr(settings, "IOT_OFFLINE_AFTER_SECONDS", 3600)
        )
        dwd_devices = [
            {
                "id": device.id,
                "station_id": device.station_id,
                "owner": device.owner.get_username(),
                "city": device.city,
                "status": device.status,
            }
            for device in DWDDevice.objects.select_related("owner").order_by("-created_at", "-id")[:20]
        ]
        return Response(
            {
                "station_name": getattr(settings, "IOT_STATION_NAME", "Arduino Uno Weather Station"),
                "fixed_city": getattr(settings, "IOT_FIXED_CITY", "Saransk"),
                "status": station["status"],
                "connection_mode": config.connection_mode,
                "linked_device": config_payload["linked_device"],
                "last_seen": station["last_seen"],
                "last_reading": station["last_reading"],
                "serial": config_payload["serial"],
                "mqtt": {
                    "broker": getattr(settings, "MQTT_BROKER_NAME", "mosquitto"),
                    "status": check_mqtt(),
                    "topic": getattr(settings, "MQTT_TOPIC", "weather/station"),
                },
                "dwd_devices": dwd_devices,
            },
            status=status.HTTP_200_OK,
        )


class AdminIotConfigView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only IoT connection mode and Serial Bridge configuration.",
        responses=documented_responses(),
    )
    def get(self, _request):
        return Response(serialize_iot_config(get_iot_config()), status=status.HTTP_200_OK)

    @extend_schema(
        description="Admin-only update of IoT connection mode and Serial Bridge configuration.",
        request=AdminIotConfigSerializer,
        responses=documented_responses(),
    )
    def patch(self, request):
        config = get_iot_config()
        serializer = AdminIotConfigSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "connection_mode" in data:
            config.connection_mode = data["connection_mode"]
        if "serial_port" in data:
            config.serial_port = str(data["serial_port"]).strip()
        if "baud_rate" in data:
            config.baud_rate = int(data["baud_rate"])
        if "linked_device_id" in data:
            linked_device_id = data["linked_device_id"]
            if linked_device_id is None:
                config.linked_device = None
            else:
                try:
                    config.linked_device = DWDDevice.objects.get(pk=linked_device_id)
                except DWDDevice.DoesNotExist:
                    return Response({"detail": "linked_device_id does not exist"}, status=status.HTTP_400_BAD_REQUEST)
        if "enabled" in data:
            config.serial_enabled = bool(data["enabled"])
            if not config.serial_enabled:
                config.serial_status = IoTConfiguration.SERIAL_STATUS_DISABLED
            elif config.serial_status == IoTConfiguration.SERIAL_STATUS_DISABLED:
                config.serial_status = IoTConfiguration.SERIAL_STATUS_DISCONNECTED

        if config.connection_mode == IoTConfiguration.CONNECTION_SERIAL_BRIDGE and config.serial_enabled and not config.serial_port:
            return Response({"detail": "serial_port is required when Serial Bridge is enabled"}, status=status.HTTP_400_BAD_REQUEST)

        if (
            config.connection_mode == IoTConfiguration.CONNECTION_SERIAL_BRIDGE
            and config.serial_enabled
            and config.linked_device_id
        ):
            linked_device = config.linked_device
            linked_device.is_enabled = True
            linked_device.status = DWDDevice.STATUS_ACTIVE
            linked_device.save(update_fields=["is_enabled", "status", "updated_at"])

        config.save()
        record_system_event(
            event="admin_config_changed",
            source="admin",
            message="IoT configuration changed",
            payload={
                "connection_mode": config.connection_mode,
                "serial_enabled": config.serial_enabled,
                "serial_port": config.serial_port,
                "baud_rate": config.baud_rate,
                "linked_device_id": config.linked_device_id,
                "user_id": request.user.pk,
            },
        )
        return Response(serialize_iot_config(config), status=status.HTTP_200_OK)


class AdminLogsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only latest structured system events.",
        parameters=[
            OpenApiParameter("level", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("source", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("event", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses=documented_responses(),
    )
    def get(self, request):
        level = str(request.query_params.get("level", "")).strip().upper()
        source = str(request.query_params.get("source", "")).strip()
        event_name = str(request.query_params.get("event", "")).strip()
        if level and level not in dict(SystemEvent.LEVEL_CHOICES):
            return Response({"detail": "invalid level"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 500)
        except ValueError:
            return Response({"detail": "limit must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        events = SystemEvent.objects.all()
        if level:
            events = events.filter(level=level)
        if source:
            events = events.filter(source=source)
        if event_name:
            events = events.filter(event=event_name)

        return Response(
            [system_event_to_payload(obj) for obj in events.order_by("-timestamp", "-id")[:limit]],
            status=status.HTTP_200_OK,
        )
