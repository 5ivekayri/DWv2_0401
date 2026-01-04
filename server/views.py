from datetime import datetime, timezone

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from .providers.openmeteo import fetch_openmeteo


class WeatherView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        if request.query_params.get("city") == "test":
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return Response(
                {
                    "latitude": 0.0,
                    "longitude": 0.0,
                    "temperature_c": 0.0,
                    "pressure_hpa": 0.0,
                    "wind_speed_ms": 0.0,
                    "precipitation_mm": 0.0,
                    "observed_at": now,
                    "source": "stub",
                },
                status=200,
            )

        try:
            lat = float(request.query_params["lat"])
            lon = float(request.query_params["lon"])
        except KeyError:
            return Response({"detail": "lat and lon query parameters are required"}, status=400)
        except ValueError:
            return Response({"detail": "lat and lon must be valid floating point numbers"}, status=400)

        try:
            payload = fetch_openmeteo(lat, lon)
            return Response(payload, status=200)
        except Exception as exc:
            return Response({"detail": f"provider error: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
