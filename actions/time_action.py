"""Time action helpers."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from actions.location_action import current_location


def current_local_time(location: str) -> str:
    """Resolve local time from IANA timezone or human-readable location text."""
    tz_key = location.strip()
    if not tz_key:
        preferred_or_detected = current_location()
        tz_key = preferred_or_detected.get("timezone") or ""
        if not tz_key:
            raise ValueError("No timezone available from saved preference or detected location.")
    try:
        return datetime.now(ZoneInfo(tz_key)).strftime("%a, %d %b %Y %H:%M:%S %z")
    except ZoneInfoNotFoundError:
        detected = current_location()
        detected_city = (detected.get("city") or "").lower()
        detected_region = (detected.get("region") or "").lower()
        lowered = tz_key.lower()
        if (
            detected.get("timezone")
            and ((detected_city and detected_city in lowered) or (detected_region and detected_region in lowered))
        ):
            return datetime.now(ZoneInfo(detected["timezone"])).strftime("%a, %d %b %Y %H:%M:%S %z")

        query = location.strip()
        parts = [p.strip() for p in query.split(",") if p.strip()]
        queries = [query] if query else []
        if parts:
            queries.extend(
                candidate
                for candidate in [
                    parts[0],
                    ", ".join(parts[:2]) if len(parts) >= 2 else "",
                    ", ".join([parts[0], parts[-1]]) if len(parts) >= 2 else "",
                    parts[-1] if len(parts) >= 2 else "",
                ]
                if candidate and candidate not in queries
            )

        for candidate_query in queries:
            response = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": candidate_query, "count": 1, "language": "en", "format": "json"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results") or []
            if results and results[0].get("timezone"):
                timezone_key = results[0]["timezone"]
                return datetime.now(ZoneInfo(timezone_key)).strftime("%a, %d %b %Y %H:%M:%S %z")

        raise ValueError(
            f"Unsupported timezone/location '{location}'. Use an IANA timezone like America/Los_Angeles."
        )


def run_time_action(location: str) -> str:
    """Execute the time action and return a one-line observation."""
    local_time = current_local_time(location)
    return f"Current local time in {location} is {local_time}."
