from __future__ import annotations

import requests


OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


def geocode_city(*, city: str, limit: int = 5, language: str = "ru") -> list[dict]:
    response = requests.get(
        OPEN_METEO_GEOCODING_URL,
        params={
            "name": city,
            "count": limit,
            "language": language,
            "format": "json",
        },
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()
    results = data.get("results") or []

    return [
        {
            "name": item.get("name", ""),
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "country": item.get("country", ""),
            "country_code": item.get("country_code", ""),
            "admin1": item.get("admin1", ""),
            "timezone": item.get("timezone", ""),
        }
        for item in results
        if "latitude" in item and "longitude" in item
    ]
