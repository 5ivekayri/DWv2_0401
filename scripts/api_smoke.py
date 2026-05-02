from __future__ import annotations

import os
import sys
import time
from typing import Any

import requests


BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PASSWORD = "password123"


def request_json(method: str, path: str, *, expected: tuple[int, ...], **kwargs: Any) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    response = requests.request(method, url, timeout=20, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:300]}

    if response.status_code not in expected:
        raise AssertionError(f"{method} {path} -> {response.status_code}, expected {expected}, body={payload}")

    print(f"PASS {method} {path} -> {response.status_code}")
    return payload


def main() -> int:
    run_id = int(time.time())
    username = f"smoke_{run_id}"
    email = f"smoke_{run_id}@example.com"
    station_id = f"arduino-smoke-{run_id}"

    request_json("GET", "/api/health", expected=(200,))

    signup = request_json(
        "POST",
        "/api/auth/signup/",
        expected=(201,),
        json={"username": username, "email": email, "password": PASSWORD},
    )
    assert signup["username"] == username

    tokens = request_json(
        "POST",
        "/api/auth/login/",
        expected=(200,),
        json={"username": email, "password": PASSWORD},
    )
    access = tokens["access"]
    auth_headers = {"Authorization": f"Bearer {access}"}

    geocode = request_json("GET", "/api/geocode", expected=(200,), params={"city": "Саранск, Россия", "limit": 1})
    place = geocode["results"][0]
    lat = place["latitude"]
    lon = place["longitude"]

    weather = request_json("GET", "/api/weather", expected=(200,), params={"lat": lat, "lon": lon})
    for key in ("temperature_c", "pressure_hpa", "wind_speed_ms", "precipitation_mm", "cache_status"):
        assert key in weather, f"weather response misses {key}"

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
