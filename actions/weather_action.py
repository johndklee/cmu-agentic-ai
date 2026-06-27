"""Weather action helpers."""

import requests

from preferences import load_preferences


def resolve_location_details(location: str) -> dict:
    """Resolve free-text location into coordinates and timezone for weather lookup."""
    query = location.strip()
    if not query:
        raise ValueError("weather[location] requires a non-empty location.")

    parts = [p.strip() for p in query.split(",") if p.strip()]
    queries = [query]
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

    result = None
    for candidate_query in queries:
        response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": candidate_query, "count": 1, "language": "en", "format": "json"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        if results:
            result = results[0]
            break

    if not result:
        raise ValueError(f"Could not resolve location '{location}' for weather lookup.")

    return {
        "name": ", ".join(
            part for part in [result.get("name"), result.get("admin1"), result.get("country")] if part
        ),
        "latitude": result["latitude"],
        "longitude": result["longitude"],
        "timezone": result.get("timezone") or "UTC",
    }


def fetch_weather_snapshot(location: str) -> dict:
    """Fetch structured current weather details for a provided location."""
    details = resolve_location_details(location)
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": details["latitude"],
            "longitude": details["longitude"],
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": details["timezone"],
            "forecast_days": 1,
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    current = data.get("current", {})
    daily = data.get("daily", {})
    weather_codes = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        80: "Rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        95: "Thunderstorm",
    }
    return {
        "location": {
            "name": details["name"],
            "latitude": details["latitude"],
            "longitude": details["longitude"],
            "timezone": details["timezone"],
        },
        "description": weather_codes.get(current.get("weather_code"), "Unknown conditions"),
        "temperature_c": current.get("temperature_2m"),
        "apparent_temperature_c": current.get("apparent_temperature"),
        "high_c": (daily.get("temperature_2m_max") or [None])[0],
        "low_c": (daily.get("temperature_2m_min") or [None])[0],
        "wind_kmh": current.get("wind_speed_10m"),
        "weather_code": current.get("weather_code"),
    }


def current_weather(location: str) -> str:
    """Fetch and format current weather conditions for a provided location."""
    snapshot = fetch_weather_snapshot(location)
    details = snapshot["location"]
    preferences = load_preferences()
    temp_unit = (preferences.get("temperature_unit") or "C").upper()
    use_fahrenheit = temp_unit == "F"

    def convert_temp(celsius: float):
        if celsius is None:
            return None
        return (celsius * 9 / 5) + 32 if use_fahrenheit else celsius

    unit_label = "F" if use_fahrenheit else "C"
    description = snapshot["description"]
    current_temp = convert_temp(snapshot.get("temperature_c"))
    apparent_temp = convert_temp(snapshot.get("apparent_temperature_c"))
    high = convert_temp(snapshot.get("high_c"))
    low = convert_temp(snapshot.get("low_c"))
    return (
        f"Current weather in {details['name']}: {description}, {current_temp:.1f}{unit_label} "
        f"(feels like {apparent_temp:.1f}{unit_label}), wind {snapshot.get('wind_kmh')} km/h, "
        f"high {high:.1f}{unit_label}, low {low:.1f}{unit_label}."
    )


def run_weather_action(location: str) -> str:
    """Execute the weather action and return a one-line observation."""
    return current_weather(location)
