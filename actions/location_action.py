"""Location action and session location state helpers."""

import requests

from preferences import load_preferences


SESSION_LOCATION = None


def detect_current_location() -> dict:
    """Detect current location details from the ipinfo service."""
    data = requests.get("https://ipinfo.io/json", timeout=10).json()
    return {
        "city": data.get("city"),
        "region": data.get("region"),
        "country": data.get("country"),
        "latlon": data.get("loc"),
        "timezone": data.get("timezone"),
    }


def current_location() -> dict:
    """Return session location, preferring saved user preference when present."""
    global SESSION_LOCATION
    preferences = load_preferences()
    saved = preferences.get("preferred_location")
    if isinstance(saved, dict) and any(saved.get(k) for k in ("city", "region", "country", "timezone", "latlon")):
        SESSION_LOCATION = saved
        return saved
    location_text = (preferences.get("preferred_location_text") or "").strip()
    if location_text:
        try:
            from preferences import resolve_preferred_location, save_preferences
            resolved = resolve_preferred_location(location_text)
            preferences["preferred_location"] = resolved
            save_preferences(preferences)
            SESSION_LOCATION = resolved
            return resolved
        except Exception:
            pass
    if SESSION_LOCATION is None:
        SESSION_LOCATION = detect_current_location()
    return SESSION_LOCATION


def format_location(location: dict) -> str:
    """Format a location dict into a readable city/region/country string."""
    return ", ".join(
        part for part in [location.get("city"), location.get("region"), location.get("country")] if part
    )


def location_identity(location: dict) -> tuple:
    """Build a normalized tuple for comparing two location records."""
    if not isinstance(location, dict):
        return ("", "", "", "")
    return tuple((location.get(key) or "").strip().lower() for key in ("city", "region", "country", "timezone"))


def resolve_session_location_from_preferences(preferences: dict, display_panel_fn) -> bool:
    """Choose session location from saved preference vs detected location, prompting on mismatch."""
    global SESSION_LOCATION
    detected = detect_current_location()
    preferences["last_detected_location"] = detected

    saved = preferences.get("preferred_location")
    changed = False
    if not isinstance(saved, dict) or not saved:
        preferences["preferred_location"] = detected
        SESSION_LOCATION = detected
        display_panel_fn(
            f"Saved initial location preference: {format_location(detected)}",
            title="Location Preference",
            border_style="blue",
        )
        return True

    if location_identity(saved) != location_identity(detected):
        display_panel_fn(
            "Detected a different current location than your saved preference.\n"
            f"Saved preference: {format_location(saved)}\n"
            f"Detected now: {format_location(detected)}",
            title="Location Change Detected",
            border_style="yellow",
        )
        while True:
            response = input(
                "Use this newly detected location as your preference for this session (and save it)? (yes/no): "
            ).strip().lower()
            if response in {"yes", "y"}:
                preferences["preferred_location"] = detected
                preferences["preferred_location_text"] = format_location(detected)
                changed = True
                SESSION_LOCATION = detected
                break
            if response in {"no", "n", ""}:
                SESSION_LOCATION = saved
                break
            print("Please answer with 'yes' or 'no'.")
    else:
        SESSION_LOCATION = saved

    return changed


def run_location_action() -> str:
    """Execute the location action and return a one-line observation."""
    location = current_location()
    return f"Current location is {location['city']}, {location['region']}, {location['country']}."
