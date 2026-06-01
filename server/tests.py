from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from django.utils import timezone as django_timezone

from server.models import (
    DWDDevice,
    DWDDeviceEvent,
    DWDNotification,
    DWDProviderApplication,
    DWDProvisioning,
    DWDSupportMessage,
    ExtendedWeatherSnapshot,
    IoTConfiguration,
    ProviderHealth,
    StationRequestLog,
    SystemEvent,
    WeatherStationReading,
    WeatherHourlySnapshot,
)
from server.iot.config import get_iot_config
from server.iot.mqtt_bridge import MqttArduinoListener, parse_mqtt_message
from server.iot.serial_bridge import SerialArduinoReader, parse_serial_line
from server.weather.contracts import WeatherPoint
from server.weather.storage import get_hour_bucket, normalize_coordinate


LOC_MEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}

STATION_KEY_HEADER = {"HTTP_X_STATION_KEY": "dev-station-key"}


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
        self.assertNotIn("visual_crossing", {item["name"] for item in stats.data["providers"]})

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

    def test_extended_weather_requires_auth(self):
        response = self.client.get("/api/weather/extended/", {"lat": "54.1838", "lon": "45.1749", "days": "7"})

        self.assertEqual(response.status_code, 401)

    @override_settings(VISUAL_CROSSING_API_KEY="test-key")
    def test_extended_weather_uses_fresh_db_snapshot_without_provider_call(self):
        user = get_user_model().objects.create_user(username="extended-user", password="password123")
        ExtendedWeatherSnapshot.objects.create(
            city="Saransk",
            location="Saransk, Russia",
            latitude=normalize_coordinate(54.1838),
            longitude=normalize_coordinate(45.1749),
            source="visual_crossing",
            forecast_days=7,
            payload_json={"provider": "visual_crossing"},
            normalized_daily_json=[
                {
                    "date": "2026-05-12",
                    "temp_min": 8.2,
                    "temp_max": 17.4,
                    "humidity": 65,
                    "wind_speed": 5.1,
                    "precip_probability": 40,
                    "conditions": "Rain",
                }
            ],
            normalized_hourly_json=[],
            expires_at=django_timezone.now() + timedelta(hours=1),
        )

        self.client.force_authenticate(user=user)
        with patch("server.weather.visual_crossing.VisualCrossingClient.fetch_forecast") as fetch_forecast:
            response = self.client.get(
                "/api/weather/extended/",
                {"lat": "54.1838", "lon": "45.1749", "days": "7"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["cached"])
        self.assertEqual(response.data["source"], "visual_crossing")
        self.assertEqual(response.data["daily"][0]["conditions"], "Rain")
        fetch_forecast.assert_not_called()

    @override_settings(VISUAL_CROSSING_API_KEY="test-key")
    def test_extended_weather_calls_visual_crossing_once_and_reuses_db(self):
        user = get_user_model().objects.create_user(username="extended-live", password="password123")
        payload = {
            "resolvedAddress": "Saransk, Mordovia, Russia",
            "days": [
                {
                    "datetime": "2026-05-12",
                    "tempmin": 8.2,
                    "tempmax": 17.4,
                    "humidity": 65,
                    "windspeed": 18.36,
                    "precipprob": 40,
                    "conditions": "Rain",
                    "hours": [
                        {
                            "datetime": "12:00:00",
                            "temp": 13.1,
                            "humidity": 60,
                            "windspeed": 10.8,
                            "precipprob": 20,
                            "conditions": "Cloudy",
                        }
                    ],
                }
            ],
        }

        self.client.force_authenticate(user=user)
        with patch("server.weather.visual_crossing.VisualCrossingClient.fetch_forecast", return_value=payload) as fetch_forecast:
            first = self.client.get("/api/weather/extended/", {"lat": "54.1838", "lon": "45.1749", "days": "7"})
            second = self.client.get("/api/weather/extended/", {"lat": "54.1838", "lon": "45.1749", "days": "7"})

        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.data["cached"])
        self.assertEqual(first.data["daily"][0]["wind_speed"], 5.1)
        self.assertEqual(first.data["hourly"][0]["date"], "2026-05-12")
        self.assertEqual(first.data["hourly"][0]["time"], "12:00")
        self.assertEqual(first.data["hourly"][0]["wind_speed"], 3.0)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["cached"])
        self.assertEqual(second.data["hourly"][0]["time"], "12:00")
        fetch_forecast.assert_called_once()
        self.assertEqual(ExtendedWeatherSnapshot.objects.filter(source="visual_crossing").count(), 1)

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

        created = self.client.post("/api/station/readings", payload, format="json", **STATION_KEY_HEADER)
        latest = self.client.get("/api/station/latest", {"station_id": "arduino-test"})
        history = self.client.get("/api/station/history", {"station_id": "arduino-test", "limit": "10"})

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data, {"status": "ok"})
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(latest.data["source"], WeatherStationReading.SOURCE_WIFI_ESP01)
        self.assertEqual(latest.data["request_ip"], "127.0.0.1")
        self.assertIsNotNone(latest.data["request_latency_ms"])
        self.assertEqual(len(history.data["results"]), 1)
        request_log = StationRequestLog.objects.get(station_id="arduino-test")
        self.assertTrue(request_log.accepted)
        self.assertEqual(request_log.status_code, 201)

    def test_station_ingest_rejects_invalid_station_key_and_logs_request(self):
        response = self.client.post(
            "/api/station/readings",
            {"station_id": "arduino-test", "temperature_c": 27.1, "humidity": 20},
            format="json",
            HTTP_X_STATION_KEY="wrong-key",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(WeatherStationReading.objects.exists())
        request_log = StationRequestLog.objects.get(station_id="arduino-test")
        self.assertFalse(request_log.accepted)
        self.assertEqual(request_log.status_code, 403)
        self.assertEqual(request_log.error, "invalid station key")

    def test_station_requests_endpoint_returns_recent_admin_logs(self):
        owner = get_user_model().objects.create_user(username="station-owner", password="password123")
        DWDDevice.objects.create(
            owner=owner,
            device_code="DWD Test Station",
            station_id="arduino-test",
            city="Саранск",
            status=DWDDevice.STATUS_ACTIVE,
        )
        self.client.post(
            "/api/station/readings",
            {"station_id": "arduino-test", "temperature_c": 27.1, "humidity": 20},
            format="json",
            **STATION_KEY_HEADER,
        )
        user = get_user_model().objects.create_user(username="station-admin", password="password123", is_staff=True)
        self.client.force_authenticate(user=user)

        response = self.client.get("/api/station/requests", {"station_id": "arduino-test"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertTrue(response.data["results"][0]["accepted"])
        self.assertEqual(response.data["results"][0]["raw_payload"]["temperature_c"], 27.1)
        self.assertEqual(response.data["results"][0]["station_name"], "DWD Test Station")
        self.assertEqual(response.data["results"][0]["city"], "Саранск")
        self.assertEqual(response.data["results"][0]["temperature_c"], 27.1)

    def test_station_ingest_links_device_by_device_code_alias_and_accepts_r4_wifi_source(self):
        owner = get_user_model().objects.create_user(username="r4-owner", password="password123")
        device = DWDDevice.objects.create(
            owner=owner,
            device_code="dwd-3",
            station_id="arduino-3",
            city="Саранск",
            status=DWDDevice.STATUS_ACTIVE,
            is_enabled=True,
        )

        response = self.client.post(
            "/api/station/readings",
            {"station_id": "dwd-3", "temperature_c": 26.1, "humidity": 23, "source": "r4_wifi"},
            format="json",
            **STATION_KEY_HEADER,
        )

        self.assertEqual(response.status_code, 201)
        reading = WeatherStationReading.objects.get(station_id="dwd-3")
        self.assertEqual(reading.device_id, device.id)
        self.assertEqual(reading.source, WeatherStationReading.SOURCE_WIFI_ESP01)

    def test_serial_bridge_parses_json_and_saves_common_station_reading(self):
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_SERIAL_BRIDGE
        config.serial_enabled = True
        config.serial_port = "COM3"
        config.baud_rate = 9600
        config.serial_status = IoTConfiguration.SERIAL_STATUS_DISCONNECTED
        config.save()

        reading = SerialArduinoReader(config=config).save_line('{"temperature":23.5,"humidity":48}')

        self.assertEqual(reading.source, WeatherStationReading.SOURCE_SERIAL_BRIDGE)
        self.assertEqual(reading.temperature_c, 23.5)
        self.assertEqual(reading.humidity, 48)
        self.assertTrue(
            WeatherStationReading.objects.filter(
                pk=reading.pk,
                source=WeatherStationReading.SOURCE_SERIAL_BRIDGE,
            ).exists()
        )

        latest = self.client.get("/api/station/latest", {"station_id": "arduino-1"})
        history = self.client.get("/api/station/history", {"station_id": "arduino-1", "limit": "10"})

        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data["source"], WeatherStationReading.SOURCE_SERIAL_BRIDGE)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data["results"][-1]["source"], WeatherStationReading.SOURCE_SERIAL_BRIDGE)

    def test_serial_bridge_parses_key_value_format(self):
        payload = parse_serial_line("temperature=23.5;humidity=48")

        self.assertEqual(payload.temperature_c, 23.5)
        self.assertEqual(payload.humidity, 48)

    def test_serial_bridge_converts_fahrenheit_when_unit_is_explicit(self):
        payload = parse_serial_line('{"temperature":78.8,"humidity":48,"unit":"fahrenheit"}')

        self.assertAlmostEqual(payload.temperature_c, 26.0, places=1)

    def test_mqtt_bridge_saves_reading_and_links_dwd_device(self):
        owner = get_user_model().objects.create_user(username="mqtt-owner", password="password123")
        device = DWDDevice.objects.create(
            owner=owner,
            device_code="dwd-3",
            station_id="dwd-3",
            city="Саранск",
            status=DWDDevice.STATUS_ACTIVE,
            firmware_type=WeatherStationReading.SOURCE_MQTT,
        )
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_MQTT
        config.mqtt_enabled = True
        config.mqtt_host = "127.0.0.1"
        config.mqtt_port = 1883
        config.mqtt_topic = "darkweather/stations/+/readings"
        config.mqtt_status = IoTConfiguration.MQTT_STATUS_DISCONNECTED
        config.save()

        reading = MqttArduinoListener(config=config).save_message(
            "darkweather/stations/dwd-3/readings",
            '{"temperature_c":26.1,"humidity":23}',
            remote_ip="192.168.0.25",
        )

        device.refresh_from_db()
        config.refresh_from_db()
        self.assertIsNotNone(reading)
        self.assertEqual(reading.device_id, device.id)
        self.assertEqual(reading.station_id, "dwd-3")
        self.assertEqual(reading.source, WeatherStationReading.SOURCE_MQTT)
        self.assertEqual(reading.temperature_c, 26.1)
        self.assertEqual(reading.humidity, 23)
        self.assertEqual(device.ip_address, "192.168.0.25")
        self.assertEqual(config.mqtt_status, IoTConfiguration.MQTT_STATUS_CONNECTED)
        request_log = StationRequestLog.objects.get(station_id="dwd-3")
        self.assertTrue(request_log.accepted)
        self.assertEqual(request_log.reading_id, reading.id)
        self.assertEqual(request_log.raw_payload["source"], WeatherStationReading.SOURCE_MQTT)

    def test_mqtt_bridge_requires_valid_payload_without_crashing(self):
        config = get_iot_config()
        config.mqtt_enabled = True
        config.save()

        reading = MqttArduinoListener(config=config).save_message("weather/station", '{"error":"dht_read_failed"}')

        self.assertIsNone(reading)
        self.assertFalse(WeatherStationReading.objects.exists())
        self.assertFalse(StationRequestLog.objects.get().accepted)
        self.assertTrue(SystemEvent.objects.filter(event="mqtt_parse_failed").exists())

    def test_mqtt_topic_can_supply_station_id(self):
        payload = parse_mqtt_message("darkweather/stations/dwd-3/readings", '{"temperature_c":26.1,"humidity":23}')

        self.assertEqual(payload.station_id, "dwd-3")
        self.assertEqual(payload.temperature_c, 26.1)

    def test_serial_bridge_linked_device_saves_fk_and_logs_normalized_temperature(self):
        owner = get_user_model().objects.create_user(username="serial-owner", password="password123")
        device = DWDDevice.objects.create(
            owner=owner,
            device_code="DWD Saransk Station",
            station_id="DWD-SARANSK-001",
            city="Saransk",
            status=DWDDevice.STATUS_ACTIVE,
            firmware_type=WeatherStationReading.SOURCE_SERIAL_BRIDGE,
        )
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_SERIAL_BRIDGE
        config.serial_enabled = True
        config.linked_device = device
        config.serial_status = IoTConfiguration.SERIAL_STATUS_CONNECTED
        config.save()

        reading = SerialArduinoReader(config=config).save_line(
            '{"station_id":"DWD-SARANSK-001","temperature":26.0,"humidity":48,"source":"serial_bridge","unit":"celsius"}'
        )

        device.refresh_from_db()
        self.assertIsNotNone(reading)
        self.assertEqual(reading.device_id, device.pk)
        self.assertEqual(reading.station_id, "DWD-SARANSK-001")
        self.assertEqual(reading.temperature_c, 26.0)
        self.assertEqual(reading.humidity, 48)
        self.assertIsNotNone(device.last_data_at)
        parsed_event = SystemEvent.objects.get(event="serial_bridge_reading_parsed")
        self.assertEqual(parsed_event.payload["raw_temperature"], 26.0)
        self.assertEqual(parsed_event.payload["normalized_temperature"], 26.0)
        self.assertEqual(parsed_event.payload["station_id"], "DWD-SARANSK-001")

    def test_serial_bridge_rejects_mismatched_station_id_for_linked_device(self):
        owner = get_user_model().objects.create_user(username="serial-mismatch", password="password123")
        device = DWDDevice.objects.create(
            owner=owner,
            device_code="DWD Saransk Station",
            station_id="DWD-SARANSK-001",
            city="Saransk",
            status=DWDDevice.STATUS_ACTIVE,
            firmware_type=WeatherStationReading.SOURCE_SERIAL_BRIDGE,
        )
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_SERIAL_BRIDGE
        config.serial_enabled = True
        config.linked_device = device
        config.serial_status = IoTConfiguration.SERIAL_STATUS_CONNECTED
        config.save()

        reading = SerialArduinoReader(config=config).save_line(
            '{"station_id":"OTHER-STATION","temperature":26.0,"humidity":48,"source":"serial_bridge"}'
        )

        config.refresh_from_db()
        self.assertIsNone(reading)
        self.assertEqual(config.serial_status, IoTConfiguration.SERIAL_STATUS_CONNECTED)
        self.assertFalse(WeatherStationReading.objects.exists())
        self.assertTrue(
            SystemEvent.objects.filter(
                event="serial_bridge_parse_failed",
                message__contains="does not match linked device",
            ).exists()
        )

    def test_station_latest_by_city_uses_active_dwd_device_reading(self):
        owner = get_user_model().objects.create_user(username="city-station-owner", password="password123")
        device = DWDDevice.objects.create(
            owner=owner,
            device_code="DWD Saransk Station",
            station_id="DWD-SARANSK-001",
            city="Saransk",
            status=DWDDevice.STATUS_ACTIVE,
            is_enabled=True,
            firmware_type=WeatherStationReading.SOURCE_SERIAL_BRIDGE,
        )
        WeatherStationReading.objects.create(
            device=device,
            station_id=device.station_id,
            temperature_c=26.0,
            humidity=48,
            wind_speed_ms=0.0,
            precipitation_mm=0.0,
            observed_at=django_timezone.now(),
            source=WeatherStationReading.SOURCE_SERIAL_BRIDGE,
        )

        latest = self.client.get("/api/station/latest", {"city": "Saransk, Russia"})
        history = self.client.get("/api/station/history", {"city": "Saransk, Russia", "limit": "10"})

        self.assertEqual(latest.status_code, 200)
        self.assertTrue(latest.data["available"])
        self.assertEqual(latest.data["station"]["station_id"], "DWD-SARANSK-001")
        self.assertEqual(latest.data["reading"]["temperature"], 26.0)
        self.assertEqual(latest.data["reading"]["humidity"], 48)
        self.assertEqual(history.status_code, 200)
        self.assertTrue(history.data["available"])
        self.assertEqual(history.data["results"][-1]["device_id"], device.pk)

    def test_station_latest_by_city_without_station_returns_soft_empty_response(self):
        response = self.client.get("/api/station/latest", {"city": "NoStationCity"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["available"])
        self.assertEqual(response.data["message"], "No active station for this city")

    def test_serial_bridge_ignores_sensor_error_without_stopping_reader(self):
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_SERIAL_BRIDGE
        config.serial_enabled = True
        config.serial_status = IoTConfiguration.SERIAL_STATUS_CONNECTED
        config.save()

        reading = SerialArduinoReader(config=config).save_line('{"error":"dht_read_failed"}')

        config.refresh_from_db()
        self.assertIsNone(reading)
        self.assertEqual(config.serial_status, IoTConfiguration.SERIAL_STATUS_CONNECTED)
        self.assertFalse(WeatherStationReading.objects.exists())
        self.assertTrue(
            SystemEvent.objects.filter(
                event="serial_bridge_parse_failed",
                source="serial_bridge",
                message__contains="dht_read_failed",
            ).exists()
        )

    def test_serial_bridge_ignores_invalid_json_without_stopping_reader(self):
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_SERIAL_BRIDGE
        config.serial_enabled = True
        config.serial_status = IoTConfiguration.SERIAL_STATUS_CONNECTED
        config.save()

        reading = SerialArduinoReader(config=config).save_line('{"temperature":')

        config.refresh_from_db()
        self.assertIsNone(reading)
        self.assertEqual(config.serial_status, IoTConfiguration.SERIAL_STATUS_CONNECTED)
        self.assertFalse(WeatherStationReading.objects.exists())
        self.assertTrue(SystemEvent.objects.filter(event="serial_bridge_parse_failed").exists())

    def test_serial_bridge_read_loop_logs_open_attempt_raw_line_and_received_data(self):
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_SERIAL_BRIDGE
        config.serial_enabled = True
        config.serial_port = "COM6"
        config.baud_rate = 9600
        config.serial_status = IoTConfiguration.SERIAL_STATUS_DISCONNECTED
        config.save()

        class FakeSerialConnection:
            def __init__(self, port, baud_rate, timeout):
                self.port = port
                self.baud_rate = baud_rate
                self.timeout = timeout
                self.calls = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def readline(self):
                self.calls += 1
                config.serial_enabled = False
                config.save(update_fields=["serial_enabled", "updated_at"])
                return b'{"temperature":26.0,"humidity":48,"source":"serial_bridge"}\n'

        fake_serial = SimpleNamespace(Serial=FakeSerialConnection)

        with patch("server.iot.serial_bridge.importlib.import_module", return_value=fake_serial):
            SerialArduinoReader(config=config)._read_loop_once()

        self.assertTrue(SystemEvent.objects.filter(event="serial_bridge_open_attempted", payload__port="COM6").exists())
        self.assertTrue(SystemEvent.objects.filter(event="serial_bridge_connected", payload__port="COM6").exists())
        raw_event = SystemEvent.objects.get(event="serial_bridge_raw_line_received")
        self.assertEqual(raw_event.payload["raw_line"], '{"temperature":26.0,"humidity":48,"source":"serial_bridge"}')
        self.assertEqual(raw_event.payload["raw_bytes_length"], 60)
        self.assertTrue(SystemEvent.objects.filter(event="serial_bridge_reading_received").exists())
        self.assertEqual(WeatherStationReading.objects.get().temperature_c, 26.0)

    @override_settings(SERIAL_BRIDGE_EMPTY_READ_LOG_INTERVAL_SECONDS=0)
    def test_serial_bridge_read_loop_logs_timeout_when_no_data_arrives(self):
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_SERIAL_BRIDGE
        config.serial_enabled = True
        config.serial_port = "COM6"
        config.baud_rate = 9600
        config.serial_status = IoTConfiguration.SERIAL_STATUS_DISCONNECTED
        config.save()

        class EmptySerialConnection:
            def __init__(self, port, baud_rate, timeout):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def readline(self):
                config.serial_enabled = False
                config.save(update_fields=["serial_enabled", "updated_at"])
                return b""

        fake_serial = SimpleNamespace(Serial=EmptySerialConnection)

        with patch("server.iot.serial_bridge.importlib.import_module", return_value=fake_serial):
            SerialArduinoReader(config=config)._read_loop_once()

        timeout_event = SystemEvent.objects.get(event="serial_bridge_readline_timeout")
        self.assertEqual(timeout_event.level, SystemEvent.LEVEL_WARNING)
        self.assertEqual(timeout_event.payload["port"], "COM6")
        self.assertFalse(WeatherStationReading.objects.exists())

    def test_serial_bridge_read_loop_logs_port_error_when_com_port_is_unavailable(self):
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_SERIAL_BRIDGE
        config.serial_enabled = True
        config.serial_port = "COM6"
        config.baud_rate = 9600
        config.serial_status = IoTConfiguration.SERIAL_STATUS_DISCONNECTED
        config.save()

        def raise_port_error(*_args, **_kwargs):
            raise OSError("Access is denied")

        fake_serial = SimpleNamespace(Serial=raise_port_error)

        with patch("server.iot.serial_bridge.time.sleep"):
            with patch("server.iot.serial_bridge.importlib.import_module", return_value=fake_serial):
                SerialArduinoReader(config=config)._read_loop_once()

        config.refresh_from_db()
        self.assertEqual(config.serial_status, IoTConfiguration.SERIAL_STATUS_ERROR)
        self.assertIn("Access is denied", config.serial_last_error)
        self.assertTrue(SystemEvent.objects.filter(event="serial_bridge_open_attempted", payload__port="COM6").exists())
        self.assertTrue(SystemEvent.objects.filter(event="serial_bridge_port_error", message__contains="Access is denied").exists())
        self.assertTrue(SystemEvent.objects.filter(event="serial_bridge_disconnected", payload__error__contains="Access is denied").exists())


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
        self.assertTrue({"openmeteo", "openweather", "yandex", "visual_crossing"}.issubset(names))
        visual_crossing = next(item for item in response.data if item["name"] == "visual_crossing")
        self.assertFalse(visual_crossing["race_enabled"])
        self.assertTrue(visual_crossing["rich_provider"])

    def test_race_stats_excludes_visual_crossing_provider_health(self):
        ProviderHealth.objects.create(
            name="visual_crossing",
            enabled=True,
            status=ProviderHealth.STATUS_OK,
            success_count=5,
            win_count=5,
        )
        self.client.force_authenticate(user=self.admin)

        response = self.client.get("/api/admin/race/stats/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("visual_crossing", {item["name"] for item in response.data["providers"]})

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
            **STATION_KEY_HEADER,
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/admin/iot/status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "online")
        self.assertEqual(response.data["last_reading"]["temperature"], 22.0)
        self.assertEqual(response.data["last_reading"]["humidity"], 45.0)
        self.assertEqual(response.data["last_reading"]["source"], WeatherStationReading.SOURCE_WIFI_ESP01)

    def test_iot_config_requires_admin_and_updates_serial_bridge(self):
        device = DWDDevice.objects.create(
            owner=self.admin,
            device_code="DWD Saransk Station",
            station_id="DWD-SARANSK-001",
            city="Saransk",
            status=DWDDevice.STATUS_INACTIVE,
            is_enabled=False,
        )
        anonymous = self.client.get("/api/admin/iot/config/")
        self.assertEqual(anonymous.status_code, 401)

        self.client.force_authenticate(user=self.user)
        forbidden = self.client.patch(
            "/api/admin/iot/config/",
            {
                "connection_mode": "serial_bridge",
                "serial_port": "COM3",
                "baud_rate": 9600,
                "linked_device_id": device.pk,
                "enabled": True,
            },
            format="json",
        )
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_authenticate(user=self.admin)
        updated = self.client.patch(
            "/api/admin/iot/config/",
            {
                "connection_mode": "serial_bridge",
                "serial_port": "COM3",
                "baud_rate": 9600,
                "linked_device_id": device.pk,
                "enabled": True,
            },
            format="json",
        )
        fetched = self.client.get("/api/admin/iot/config/")

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["connection_mode"], IoTConfiguration.CONNECTION_SERIAL_BRIDGE)
        self.assertEqual(updated.data["serial_port"], "COM3")
        self.assertEqual(updated.data["baud_rate"], 9600)
        self.assertEqual(updated.data["linked_device"]["id"], device.pk)
        self.assertEqual(updated.data["linked_device"]["city"], "Saransk")
        self.assertTrue(updated.data["enabled"])
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.data["serial"]["status"], IoTConfiguration.SERIAL_STATUS_DISCONNECTED)
        self.assertEqual(fetched.data["serial"]["linked_device"]["station_id"], "DWD-SARANSK-001")
        device.refresh_from_db()
        self.assertEqual(device.status, DWDDevice.STATUS_ACTIVE)
        self.assertTrue(device.is_enabled)

    def test_iot_status_includes_serial_bridge_status(self):
        config = get_iot_config()
        config.connection_mode = IoTConfiguration.CONNECTION_SERIAL_BRIDGE
        config.serial_enabled = True
        config.serial_port = "COM3"
        config.baud_rate = 9600
        config.serial_status = IoTConfiguration.SERIAL_STATUS_CONNECTED
        config.save()

        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/admin/iot/status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["connection_mode"], IoTConfiguration.CONNECTION_SERIAL_BRIDGE)
        self.assertEqual(response.data["serial"]["port"], "COM3")
        self.assertEqual(response.data["serial"]["baud_rate"], 9600)
        self.assertEqual(response.data["serial"]["status"], IoTConfiguration.SERIAL_STATUS_CONNECTED)

    def test_iot_config_updates_mqtt_settings(self):
        self.client.force_authenticate(user=self.admin)

        updated = self.client.patch(
            "/api/admin/iot/config/",
            {
                "connection_mode": "mqtt",
                "mqtt_enabled": True,
                "mqtt_host": "127.0.0.1",
                "mqtt_port": 1883,
                "mqtt_topic": "darkweather/stations/+/readings",
                "mqtt_username": "mqtt-user",
                "mqtt_password": "mqtt-secret",
            },
            format="json",
        )
        fetched = self.client.get("/api/admin/iot/config/")

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["connection_mode"], IoTConfiguration.CONNECTION_MQTT)
        self.assertTrue(updated.data["mqtt"]["enabled"])
        self.assertEqual(updated.data["mqtt"]["host"], "127.0.0.1")
        self.assertEqual(updated.data["mqtt"]["port"], 1883)
        self.assertEqual(updated.data["mqtt"]["topic"], "darkweather/stations/+/readings")
        self.assertEqual(updated.data["mqtt"]["username"], "mqtt-user")
        self.assertTrue(updated.data["mqtt"]["has_password"])
        self.assertEqual(fetched.data["mqtt"]["status"], IoTConfiguration.MQTT_STATUS_DISCONNECTED)


@override_settings(CACHES=LOC_MEM_CACHE)
class DWDProviderApplicationApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(username="provider-user", password="password123")
        self.admin = User.objects.create_user(username="admin-user", password="password123", is_staff=True)

    def create_application(self, *, city="Berlin"):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/provider-applications/",
            {"city": city, "email": "device-contact@example.com", "comment": "I want to connect my DWD device."},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        return DWDProviderApplication.objects.get(pk=response.data["id"])

    def approve_application(self, application):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/admin/dwd/applications/{application.pk}/approve/")
        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        return response

    def test_application_requires_city_and_email(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/provider-applications/",
            {"comment": "I want to connect my DWD device."},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("city", response.data)
        self.assertIn("email", response.data)

    def test_application_with_city_is_created(self):
        application = self.create_application(city="Berlin")

        self.assertEqual(application.city, "Berlin")
        self.assertEqual(application.email, "device-contact@example.com")
        self.assertEqual(application.user, self.user)
        self.assertEqual(application.status, DWDProviderApplication.STATUS_PENDING)
        self.assertTrue(
            DWDNotification.objects.filter(
                recipient=self.admin,
                notification_type=DWDNotification.TYPE_APPLICATION_SUBMITTED,
                application=application,
            ).exists()
        )

    def test_user_cannot_create_second_pending_application(self):
        self.create_application(city="Berlin")
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/provider-applications/",
            {"city": "Paris", "email": "other@example.com", "comment": "Second device."},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_approve_grants_provider_group_and_creates_device_with_city(self):
        application = self.create_application(city="Saransk")

        response = self.approve_application(application)

        self.assertEqual(response.data["status"], DWDProviderApplication.STATUS_APPROVED)
        self.assertTrue(Group.objects.get(name="provider").user_set.filter(pk=self.user.pk).exists())
        self.assertEqual(application.device.city, "Saransk")
        self.assertEqual(application.device.owner, self.user)
        self.assertEqual(application.device.status, DWDDevice.STATUS_INACTIVE)
        self.assertTrue(application.device.device_code)
        self.assertTrue(application.device.token)
        self.assertTrue(application.device.events.filter(event_type=DWDDeviceEvent.EVENT_REGISTERED).exists())
        self.assertTrue(application.support_messages.filter(is_system=True).exists())
        self.assertTrue(
            DWDNotification.objects.filter(
                recipient=self.user,
                notification_type=DWDNotification.TYPE_STATUS_CHANGED,
                application=application,
            ).exists()
        )

    @override_settings(
        MQTT_HOST="127.0.0.1",
        MQTT_PORT=1883,
        MQTT_USERNAME="darkweather_device",
        MQTT_PASSWORD="mqtt-secret",
        DWD_MQTT_PUBLIC_HOST="mqtt.darkweather.test",
    )
    def test_admin_can_create_and_mark_provisioning_sent(self):
        application = self.create_application(city="Berlin")
        self.approve_application(application)

        response = self.client.post(
            "/api/admin/dwd/provisioning/",
            {
                "application_id": application.pk,
                "user_id": self.user.pk,
                "device_id": application.device.pk,
                "firmware_type": "esp01_wifi",
                "firmware_version": "1.0.0",
                "instruction_text": "Open Arduino IDE, configure Wi-Fi and upload ESP-01 firmware.",
                "wifi_ssid": "ProviderNet",
                "wifi_password": "ProviderPass",
                "delivery_channel": "email",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        provisioning = DWDProvisioning.objects.get(pk=response.data["id"])
        self.assertEqual(provisioning.firmware_type, DWDProvisioning.FIRMWARE_ESP01_WIFI)
        self.assertIn("ESP-01", provisioning.instruction_text)
        self.assertIn('const char* WIFI_SSID = "ProviderNet";', provisioning.firmware_code)
        self.assertIn('const char* WIFI_PASSWORD = "ProviderPass";', provisioning.firmware_code)
        self.assertIn('const char* MQTT_HOST = "mqtt.darkweather.test";', provisioning.firmware_code)
        self.assertIn(f'const char* STATION_ID = "{application.device.station_id}";', provisioning.firmware_code)
        self.assertIn(f'darkweather/stations/{application.device.station_id}/readings', provisioning.firmware_code)
        self.assertTrue(response.data["wifi_configured"])
        self.assertEqual(provisioning.delivery_status, DWDProvisioning.DELIVERY_INSTRUCTION_READY)
        self.assertIsNotNone(provisioning.code_generated_at)
        application.device.refresh_from_db()
        self.assertEqual(application.device.firmware_type, DWDProvisioning.FIRMWARE_ESP01_WIFI)
        self.assertTrue(
            DWDNotification.objects.filter(
                recipient=self.user,
                notification_type=DWDNotification.TYPE_PROVISIONING_READY,
                provisioning=provisioning,
            ).exists()
        )

        sent = self.client.post(f"/api/admin/dwd/provisioning/{provisioning.pk}/mark-sent/")

        self.assertEqual(sent.status_code, 200)
        provisioning.refresh_from_db()
        self.assertEqual(provisioning.delivery_status, DWDProvisioning.DELIVERY_SENT)
        self.assertEqual(provisioning.sent_by, self.admin)
        self.assertIsNotNone(provisioning.sent_at)

    @override_settings(MQTT_HOST="127.0.0.1", MQTT_PORT=1883, DWD_MQTT_PUBLIC_HOST="mqtt.darkweather.test")
    def test_provisioning_without_wifi_creates_code_with_placeholders(self):
        application = self.create_application(city="Berlin")
        self.approve_application(application)
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            "/api/admin/dwd/provisioning/",
            {
                "application_id": application.pk,
                "device_id": application.device.pk,
                "firmware_type": "esp01_wifi",
                "firmware_version": "1.0.0",
                "delivery_channel": "manual",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["wifi_configured"])
        self.assertIn("PUT_WIFI_SSID_HERE", response.data["firmware_code"])
        self.assertIn("PUT_WIFI_PASSWORD_HERE", response.data["firmware_code"])
        self.assertNotIn("wifi_password", response.data)

    def test_admin_users_roles_and_device_events_endpoints(self):
        application = self.create_application(city="Berlin")
        self.approve_application(application)
        self.client.force_authenticate(user=self.admin)

        users = self.client.get("/api/admin/dwd/users/")
        self.assertEqual(users.status_code, 200)
        provider_user = next(item for item in users.data if item["id"] == self.user.pk)
        self.assertEqual(provider_user["role"], "provider")
        self.assertEqual(provider_user["active_application"]["city"], "Berlin")

        role = self.client.patch(
            f"/api/admin/dwd/users/{self.user.pk}/role/",
            {"role": "user"},
            format="json",
        )
        self.assertEqual(role.status_code, 200)
        self.assertEqual(role.data["role"], "user")

        note = self.client.patch(
            f"/api/admin/dwd/applications/{application.pk}/",
            {"admin_note": "Call user before provisioning."},
            format="json",
        )
        self.assertEqual(note.status_code, 200)
        self.assertEqual(note.data["admin_note"], "Call user before provisioning.")

        action = self.client.post(
            f"/api/admin/dwd/devices/{application.device.pk}/action/",
            {"action": "block"},
            format="json",
        )
        self.assertEqual(action.status_code, 200)
        self.assertEqual(action.data["status"], DWDDevice.STATUS_BLOCKED)

        events = self.client.get("/api/admin/dwd/device-events/", {"device_id": application.device.pk})
        self.assertEqual(events.status_code, 200)
        self.assertTrue(any(item["event_type"] == DWDDeviceEvent.EVENT_BLOCKED for item in events.data))

    def test_admin_can_delete_user_but_not_self(self):
        target = get_user_model().objects.create_user(
            username="delete-target",
            email="delete-target@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=self.admin)

        self_delete = self.client.delete(f"/api/admin/dwd/users/{self.admin.pk}/")
        deleted = self.client.delete(f"/api/admin/dwd/users/{target.pk}/")

        self.assertEqual(self_delete.status_code, 400)
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(get_user_model().objects.filter(pk=target.pk).exists())

    def test_provider_and_admin_can_chat_on_application(self):
        application = self.create_application(city="Berlin")

        provider_message = self.client.post(
            f"/api/provider-applications/{application.pk}/messages/",
            {"message": "Can I use Arduino R4 WiFi?"},
            format="json",
        )

        self.assertEqual(provider_message.status_code, 201)
        self.assertTrue(DWDSupportMessage.objects.filter(application=application, sender=self.user).exists())
        self.assertTrue(
            DWDNotification.objects.filter(
                recipient=self.admin,
                notification_type=DWDNotification.TYPE_CHAT_MESSAGE,
                application=application,
            ).exists()
        )

        self.client.force_authenticate(user=self.admin)
        admin_message = self.client.post(
            f"/api/admin/dwd/applications/{application.pk}/messages/",
            {"message": "Yes, we will generate MQTT firmware for it."},
            format="json",
        )
        messages = self.client.get(f"/api/admin/dwd/applications/{application.pk}/messages/")

        self.assertEqual(admin_message.status_code, 201)
        self.assertEqual(messages.status_code, 200)
        self.assertGreaterEqual(len(messages.data), 2)
        self.assertTrue(
            DWDNotification.objects.filter(
                recipient=self.user,
                notification_type=DWDNotification.TYPE_CHAT_MESSAGE,
                application=application,
            ).exists()
        )

    def test_user_cannot_read_another_application_chat(self):
        application = self.create_application(city="Berlin")
        other = get_user_model().objects.create_user(username="other-user", password="password123")
        self.client.force_authenticate(user=other)

        response = self.client.get(f"/api/provider-applications/{application.pk}/messages/")

        self.assertEqual(response.status_code, 404)

    def test_notification_endpoint_and_mark_read(self):
        application = self.create_application(city="Berlin")
        notification = DWDNotification.objects.filter(recipient=self.admin, application=application).first()
        self.client.force_authenticate(user=self.admin)

        listed = self.client.get("/api/dwd/notifications/")
        marked = self.client.post(f"/api/dwd/notifications/{notification.pk}/read/")

        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(item["id"] == notification.pk for item in listed.data))
        self.assertEqual(marked.status_code, 200)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_regular_user_cannot_manage_provisioning(self):
        application = self.create_application(city="Berlin")
        self.approve_application(application)
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/admin/dwd/provisioning/",
            {
                "application_id": application.pk,
                "firmware_type": "serial_bridge",
                "instruction_text": "Upload serial bridge firmware.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
