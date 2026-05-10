from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from server.models import WeatherHourlySnapshot
from server.weather.contracts import WeatherPoint
from server.weather.storage import get_hour_bucket, normalize_coordinate


LOC_MEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}


@override_settings(CACHES=LOC_MEM_CACHE)
class WeatherApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_weather_returns_mysql_hit_when_snapshot_exists(self):
        hour_bucket = get_hour_bucket()
        WeatherHourlySnapshot.objects.create(
            city="Saransk",
            latitude=normalize_coordinate(54.1838),
            longitude=normalize_coordinate(45.1749),
            hour_bucket=hour_bucket,
            temperature_c=4.35,
            pressure_hpa=1023.0,
            wind_speed_ms=2.18,
            precipitation_mm=0.0,
            observed_at=datetime(2026, 5, 2, 23, 21, 58, tzinfo=timezone.utc),
            provider="openweather",
            raw_payload={"source": "openweather"},
        )

        response = self.client.get("/api/weather", {"lat": "54.1838", "lon": "45.1749"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["cache_status"], "mysql_hit")
        self.assertEqual(response.data["source"], "openweather")

    def test_weather_race_stores_snapshot_by_requested_coordinates(self):
        class FakeProvider:
            name = "fake"

            def is_enabled(self):
                return True

            def get_weather(self, _lat, _lon):
                return WeatherPoint(
                    latitude=54.18,
                    longitude=45.17,
                    temperature_c=10.0,
                    pressure_hpa=1012.0,
                    wind_speed_ms=3.0,
                    precipitation_mm=0.0,
                    observed_at=datetime(2026, 5, 3, 0, 0, tzinfo=timezone.utc),
                    source="fake",
                )

        with patch("server.views._service", SimpleNamespace(providers=[FakeProvider()])):
            response = self.client.get("/api/weather", {"lat": "54.1838", "lon": "45.1749"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["cache_status"], "miss_stored")
        self.assertTrue(
            WeatherHourlySnapshot.objects.filter(
                latitude=normalize_coordinate(54.1838),
                longitude=normalize_coordinate(45.1749),
                provider="fake",
            ).exists()
        )

    def test_weather_race_updates_race_stats(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )

        class FakeProvider:
            name = "openmeteo"

            def is_enabled(self):
                return True

            def get_weather(self, _lat, _lon):
                return WeatherPoint(
                    latitude=10.0,
                    longitude=20.0,
                    temperature_c=10.0,
                    pressure_hpa=1012.0,
                    wind_speed_ms=3.0,
                    precipitation_mm=0.0,
                    observed_at=datetime(2026, 5, 3, 0, 0, tzinfo=timezone.utc),
                    source="openmeteo",
                )

        with patch("server.views._service", SimpleNamespace(providers=[FakeProvider()])):
            weather = self.client.get("/api/weather", {"lat": "10.0001", "lon": "20.0001"})

        self.assertEqual(weather.status_code, 200)

        self.client.force_authenticate(user=admin)
        stats = self.client.get("/api/admin/race/stats/")

        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.data["last_winner"], "openmeteo")
        self.assertTrue(stats.data["last_request_id"])
        openmeteo = next(item for item in stats.data["providers"] if item["name"] == "openmeteo")
        self.assertGreaterEqual(openmeteo["win_count"], 1)

    def test_weather_history_requires_jwt_and_returns_points(self):
        user = get_user_model().objects.create_user(username="tester", password="password123")
        hour_bucket = get_hour_bucket()
        WeatherHourlySnapshot.objects.create(
            latitude=55.7512,
            longitude=37.6184,
            hour_bucket=hour_bucket,
            temperature_c=8.0,
            pressure_hpa=1010.0,
            wind_speed_ms=1.0,
            precipitation_mm=0.0,
            observed_at=hour_bucket,
            provider="openmeteo",
        )

        anonymous = self.client.get("/api/weather/history", {"lat": "55.7512", "lon": "37.6184"})
        self.assertEqual(anonymous.status_code, 401)

        self.client.force_authenticate(user=user)
        response = self.client.get("/api/weather/history", {"lat": "55.7512", "lon": "37.6184", "limit": "24"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    @patch("server.views.geocode_city")
    def test_geocode_returns_city_results(self, geocode_city):
        geocode_city.return_value = [
            {
                "name": "Saransk",
                "latitude": 54.1838,
                "longitude": 45.1749,
                "country": "Russia",
            }
        ]

        response = self.client.get("/api/geocode", {"city": "Saransk", "limit": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["latitude"], 54.1838)

    @patch("server.views.OutfitRecommendationService")
    def test_ai_outfit_recommendation_returns_cached_or_generated_text(self, service_cls):
        obj = SimpleNamespace(
            city="Saransk",
            hour_bucket=datetime(2026, 5, 3, 0, 0, tzinfo=timezone.utc),
            recommendation_text="Wear a warm jacket.",
            model_name="test-model",
        )
        service = SimpleNamespace(
            client=SimpleNamespace(is_enabled=lambda: True),
            get_or_create_recommendation=lambda **_kwargs: (obj, False),
        )
        service_cls.return_value = service

        response = self.client.post(
            "/api/ai/outfit-recommendation",
            {
                "city": "Saransk",
                "temperature_c": 4.0,
                "humidity": 70,
                "wind_speed_ms": 2.0,
                "precipitation_mm": 0.0,
                "condition": "cloudy",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["source"], "db")

    def test_station_ingest_latest_and_history(self):
        payload = {
            "station_id": "arduino-test",
            "latitude": 54.1838,
            "longitude": 45.1749,
            "temperature_c": 7.5,
            "humidity": 66,
            "pressure_hpa": 1021,
            "wind_speed_ms": 1.2,
            "precipitation_mm": 0.0,
            "observed_at": "2026-05-03T00:00:00Z",
        }

        created = self.client.post("/api/station/readings", payload, format="json")
        latest = self.client.get("/api/station/latest", {"station_id": "arduino-test"})
        history = self.client.get("/api/station/history", {"station_id": "arduino-test", "limit": "10"})

        self.assertEqual(created.status_code, 201)
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.data["results"]), 1)


@override_settings(CACHES=LOC_MEM_CACHE)
class AdminMonitoringApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="user", password="password123")
        self.admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )

    def test_dashboard_requires_admin(self):
        anonymous = self.client.get("/api/admin/dashboard/")
        self.assertEqual(anonymous.status_code, 401)

        self.client.force_authenticate(user=self.user)
        forbidden = self.client.get("/api/admin/dashboard/")
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_authenticate(user=self.admin)
        allowed = self.client.get("/api/admin/dashboard/")
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("components", allowed.data)

    def test_providers_status_includes_required_providers(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get("/api/admin/providers/status/")

        self.assertEqual(response.status_code, 200)
        names = {item["name"] for item in response.data}
        self.assertTrue({"openmeteo", "openweather", "yandex"}.issubset(names))

    def test_provider_check_returns_json_error_instead_of_500(self):
        class FailingProvider:
            name = "openmeteo"

            def is_enabled(self):
                return True

            def get_weather(self, _lat, _lon):
                raise RuntimeError("provider exploded")

        self.client.force_authenticate(user=self.admin)
        with patch(
            "server.admin_views.get_provider_map",
            return_value={"yandex": None, "openweather": None, "openmeteo": FailingProvider()},
        ):
            response = self.client.post(
                "/api/admin/providers/check/",
                {"provider": "openmeteo", "lat": 55.7558, "lon": 37.6173},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "error")
        self.assertIn("provider exploded", response.data["error"])

    def test_iot_status_uses_latest_station_reading(self):
        self.client.post(
            "/api/station/readings",
            {
                "station_id": "arduino-test",
                "temperature_c": 22.0,
                "humidity": 45.0,
                "pressure_hpa": 1020,
                "wind_speed_ms": 1.0,
                "precipitation_mm": 0.0,
            },
            format="json",
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/admin/iot/status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "online")
        self.assertEqual(response.data["last_reading"]["temperature"], 22.0)
        self.assertEqual(response.data["last_reading"]["humidity"], 45.0)
