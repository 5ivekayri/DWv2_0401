from __future__ import annotations

import os
import sys
import time
from typing import Any

import requests


BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PASSWORD = "password123"
ADMIN_USERNAME = os.getenv("API_ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("API_ADMIN_PASSWORD", "")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("API_SMOKE_TIMEOUT_SECONDS", "60"))


def request_json(method: str, path: str, *, expected: tuple[int, ...], **kwargs: Any) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    response = requests.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:300]}

    if response.status_code not in expected:
        raise AssertionError(f"{method} {path} -> {response.status_code}, expected {expected}, body={payload}")

    print(f"PASS {method} {path} -> {response.status_code}")
    return payload


def login_as(username: str, password: str) -> dict[str, str]:
    tokens = request_json(
        "POST",
        "/api/auth/login/",
        expected=(200,),
        json={"username": username, "password": password},
    )
    return {"Authorization": f"Bearer {tokens['access']}"}


def main() -> int:
    run_id = int(time.time())
    username = f"smoke_{run_id}"
    email = f"smoke_{run_id}@example.com"
    register_username = f"register_smoke_{run_id}"
    register_email = f"register_smoke_{run_id}@example.com"
    station_id = f"arduino-smoke-{run_id}"

    request_json("GET", "/api/health", expected=(200,))

    signup = request_json(
        "POST",
        "/api/auth/signup/",
        expected=(201,),
        json={"username": username, "email": email, "password": PASSWORD},
    )
    assert signup["username"] == username
    auth_headers = login_as(email, PASSWORD)

    registered = request_json(
        "POST",
        "/api/auth/register/",
        expected=(201,),
        json={"username": register_username, "email": register_email, "password": PASSWORD},
    )
    assert registered["username"] == register_username
    login_as(register_email, PASSWORD)

    request_json("GET", "/api/admin/dashboard/", expected=(401,))
    request_json("GET", "/api/admin/dashboard/", expected=(403,), headers=auth_headers)

    admin_headers = None
    if ADMIN_USERNAME and ADMIN_PASSWORD:
        admin_headers = login_as(ADMIN_USERNAME, ADMIN_PASSWORD)
        request_json("GET", "/api/admin/dashboard/", expected=(200,), headers=admin_headers)

    geocode = request_json("GET", "/api/geocode", expected=(200,), params={"city": "Saransk", "limit": 1})
    place = geocode["results"][0]
    lat = place["latitude"]
    lon = place["longitude"]

    weather = request_json("GET", "/api/weather", expected=(200,), params={"lat": lat, "lon": lon})
    for key in ("temperature_c", "pressure_hpa", "wind_speed_ms", "precipitation_mm", "cache_status"):
        assert key in weather, f"weather response misses {key}"

    race_lat = round(float(lat) + (run_id % 1000) / 1_000_000, 6)
    race_lon = round(float(lon) + (run_id % 1000) / 1_000_000, 6)
    request_json("GET", "/api/weather/", expected=(200,), params={"lat": race_lat, "lon": race_lon})

    request_json(
        "POST",
        "/api/ai/outfit-recommendation",
        expected=(200, 503),
        json={
            "city": place["name"],
            "temperature_c": weather["temperature_c"],
            "humidity": 70,
            "wind_speed_ms": weather["wind_speed_ms"],
            "precipitation_mm": weather["precipitation_mm"],
            "condition": "rain" if weather["precipitation_mm"] > 0 else "cloudy",
        },
    )

    request_json(
        "GET",
        "/api/weather/history",
        expected=(200,),
        params={"lat": lat, "lon": lon, "limit": 24},
        headers=auth_headers,
    )

    request_json(
        "POST",
        "/api/station/readings",
        expected=(201,),
        json={
            "station_id": station_id,
            "latitude": lat,
            "longitude": lon,
            "temperature_c": 7.5,
            "humidity": 65,
            "pressure_hpa": 1021,
            "wind_speed_ms": 1.1,
            "precipitation_mm": 0,
        },
    )
    request_json("GET", "/api/station/latest", expected=(200,), params={"station_id": station_id})
    request_json("GET", "/api/station/history", expected=(200,), params={"station_id": station_id, "limit": 10})

    if admin_headers:
        providers = request_json("GET", "/api/admin/providers/status/", expected=(200,), headers=admin_headers)
        provider_names = {item["name"] for item in providers}
        assert {"yandex", "openweather", "openmeteo"}.issubset(provider_names)

        provider_check = request_json(
            "POST",
            "/api/admin/providers/check/",
            expected=(200,),
            headers=admin_headers,
            json={"provider": "openmeteo", "lat": lat, "lon": lon},
        )
        assert provider_check["status"] in {"ok", "error", "disabled", "not_configured"}

        race_stats = request_json("GET", "/api/admin/race/stats/", expected=(200,), headers=admin_headers)
        assert "providers" in race_stats
        assert race_stats["last_winner"]
        assert race_stats["last_request_id"]

        iot_status = request_json("GET", "/api/admin/iot/status/", expected=(200,), headers=admin_headers)
        assert iot_status["status"] in {"online", "offline"}
        assert iot_status["last_reading"]["temperature"] == 7.5
        assert iot_status["last_reading"]["humidity"] == 65

        request_json("GET", "/api/admin/logs/", expected=(200,), headers=admin_headers, params={"limit": 50})
    else:
        print("SKIP admin 200 checks: set API_ADMIN_USERNAME and API_ADMIN_PASSWORD")

    request_json("GET", "/api/schema/", expected=(200,))
    request_json("GET", "/api/docs/", expected=(200,))

    print("Smoke API checks completed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
