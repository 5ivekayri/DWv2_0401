import os
import logging
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

def fetch_openmeteo(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,pressure_msl,wind_speed_10m,precipitation",
        "timezone": "UTC",
    }

    if os.getenv("TESTING_MODE", "0") == "1":
        log.info("OpenMeteo GET %s params=%s", OPEN_METEO_URL, params)

    r = requests.get(OPEN_METEO_URL, params=params, timeout=10)

    if os.getenv("TESTING_MODE", "0") == "1":
        log.info("OpenMeteo status=%s body=%s", r.status_code, r.text[:500])

    r.raise_for_status()
    data = r.json()
    cur = data.get("current") or {}

    observed_at_str = cur.get("time")
    if observed_at_str:
        observed_at = datetime.fromisoformat(observed_at_str.replace("Z", "+00:00")).astimezone(timezone.utc)
    else:
        observed_at = datetime.now(timezone.utc)

    return {
        "latitude": lat,
        "longitude": lon,
        "temperature_c": float(cur.get("temperature_2m")),
        "pressure_hpa": float(cur.get("pressure_msl")),
        "wind_speed_ms": float(cur.get("wind_speed_10m")),
        "precipitation_mm": float(cur.get("precipitation")),
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "source": "openmeteo",
    }
