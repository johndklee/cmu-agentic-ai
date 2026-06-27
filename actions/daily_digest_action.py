"""Daily digest action helper."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from actions.location_action import current_location
from preferences import get_user_identity, load_preferences


def build_digest_title(preferences: dict) -> str:
    """Return digest title customized with stored user identity when available."""
    identity = get_user_identity(preferences)
    name = identity.get("name", "").strip()
    if name:
        return f"Daily Digest for {name}"
    return "Daily Digest"


def build_daily_digest() -> str:
    """Build structured daily digest facts for the preferred/session location."""
    preferences = load_preferences()
    preferred = preferences.get("preferred_location")
    if isinstance(preferred, dict) and any(preferred.get(k) for k in ("city", "region", "country", "timezone", "latlon")):
        location = preferred
    else:
        location = current_location()

    timezone_key = location.get("timezone") or "UTC"
    now_local = datetime.now(ZoneInfo(timezone_key))
    digest_data = {
        "title": build_digest_title(preferences),
        "location": {
            "city": location.get("city"),
            "region": location.get("region"),
            "country": location.get("country"),
            "timezone": timezone_key,
        },
        "date": now_local.strftime("%A, %B %d, %Y"),
        "time": now_local.strftime("%I:%M %p %Z").lstrip("0"),
        "available_sections": ["location", "date", "time", "weather", "news", "calendar", "tasks", "emails", "key_highlights"],
        "unavailable_sections": [],
        "notes": [],
    }
    return json.dumps(digest_data, indent=2)
