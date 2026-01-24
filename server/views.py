import os
import logging
from datetime import datetime, timezone

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from .weather.factory import build_weather_service
from .weather.contracts import WeatherPoint  # поправь путь, если у тебя contracts лежит иначе

log = logging.getLogger(__name__)

_service = build_weather_service()

@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    return Response({"status": "ok"})


class WeatherView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        testing = os.getenv("TESTING_MODE", "0") == "1"
        city = request.query_params.get("city")

        # Единственная разрешенная заглушка
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

        # Валидация координат
        try:
            lat = float(request.query_params["lat"])
            lon = float(request.query_params["lon"])
        except KeyError:
            return Response({"detail": "lat and lon query parameters are required"}, status=400)
        except ValueError:
            return Response({"detail": "lat and lon must be valid floating point numbers"}, status=400)

        providers = getattr(_service, "providers", None)
        if not providers:
            return Response({"detail": "no providers configured"}, status=status.HTTP_502_BAD_GATEWAY)

        enabled = [p for p in providers if getattr(p, "is_enabled", lambda: True)()]
        if not enabled:
            return Response({"detail": "no enabled providers (missing API keys?)"}, status=status.HTTP_502_BAD_GATEWAY)

        max_workers = min(getattr(_service, "max_workers", 4), len(enabled))
        last_exc = None

        # Race: кто быстрее дал валидный ответ — тот победил
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(p.get_weather, lat, lon): p for p in enabled}

            for fut in as_completed(futures):
                provider = futures[fut]
                name = getattr(provider, "name", provider.__class__.__name__)
                try:
                    point = fut.result()
                    if testing:
                        log.info("Weather selected provider=%s lat=%s lon=%s", name, lat, lon)

                    payload = asdict(point)
                    payload["observed_at"] = point.observed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                    return Response(payload, status=200)

                except Exception as exc:
                    last_exc = exc
                    if testing:
                        log.warning("Provider failed name=%s error=%s", name, exc)

        # Если все провайдеры упали
        return Response({"detail": f"all providers failed: {last_exc}"}, status=status.HTTP_502_BAD_GATEWAY)
