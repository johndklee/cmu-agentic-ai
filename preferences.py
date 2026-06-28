"""User preference persistence and normalization helpers."""

import json
import re
from pathlib import Path

import requests

ACTION_DIR = Path(__file__).with_name("actions")
MEMORY_DIR = Path(__file__).with_name(".memory")
CHROMA_DIR = MEMORY_DIR / "chroma"
SEMANTIC_COLLECTION = "semantic_preferences"
PROCEDURAL_COLLECTION = "procedural_preferences"
RUNTIME_COLLECTION = "runtime_preferences"
SEMANTIC_PROFILE_ID = "semantic_profile"
PROCEDURAL_RULES_ID = "procedural_rules"
RUNTIME_STATE_ID = "runtime_state"


DEFAULT_PREFERENCES = {
    "digest_feedback": [],
    "digest_preferences_summary": "",
    "email_daily_digest": None,
    "temperature_unit": "C",
    "preferred_location": None,
    "preferred_location_text": "",
    "user_name": "",
    "user_email": "",
    "user_email_aliases": [],
    "vip_email_addresses": [],
    "identity_setup_completed": False,
    "last_detected_location": None,
    "preferred_highlight_count": 5,
}

DIGEST_ONLY_DEFAULT_KEYS = {
    "digest_feedback",
    "digest_preferences_summary",
    "email_daily_digest",
    "temperature_unit",
    "preferred_highlight_count",
}


def _get_chroma_client():
    """Best-effort local Chroma client for semantic/procedural preference storage."""
    try:
        import chromadb
    except Exception:
        return None
    try:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(CHROMA_DIR))
    except Exception:
        return None


def _prefs_doc_semantic(preferences: dict) -> str:
    """Build a semantic-profile document for vector storage."""
    location = preferences.get("preferred_location") if isinstance(preferences.get("preferred_location"), dict) else {}
    location_label = _format_location(location) if location else ""
    aliases = ", ".join(preferences.get("user_email_aliases") or [])
    vips = ", ".join(preferences.get("vip_email_addresses") or [])
    return (
        f"user_name={preferences.get('user_name', '')} | "
        f"user_email={preferences.get('user_email', '')} | "
        f"aliases={aliases} | "
        f"vip_emails={vips} | "
        f"preferred_location={location_label} | "
        f"preferred_location_text={preferences.get('preferred_location_text', '')}"
    )


def _prefs_doc_procedural(preferences: dict) -> str:
    """Build a procedural-rule document for vector storage."""
    return (
        f"temperature_unit={preferences.get('temperature_unit', '')} | "
        f"email_daily_digest={preferences.get('email_daily_digest')} | "
        f"digest_preferences_summary={preferences.get('digest_preferences_summary', '')}"
    )


def _prefs_doc_runtime(preferences: dict) -> str:
    """Build a runtime-state document for vector storage."""
    feedback_count = len(preferences.get("digest_feedback") or [])
    has_location = bool(preferences.get("last_detected_location"))
    return f"digest_feedback_count={feedback_count} | has_last_detected_location={has_location}"


def _safe_json_text(value) -> str:
    """Serialize value to JSON text safely for Chroma metadata fields."""
    try:
        return json.dumps(value, ensure_ascii=True)
    except Exception:
        return ""


def _safe_parse_json_text(value, default):
    """Parse JSON-encoded metadata field safely with default fallback."""
    if not isinstance(value, str) or not value.strip():
        return default
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return default
    if default is None:
        return parsed
    return parsed if isinstance(parsed, type(default)) else default


def _upsert_preferences_to_vector(preferences: dict) -> None:
    """Persist semantic/procedural preferences into dedicated Chroma collections."""
    client = _get_chroma_client()
    if client is None:
        return

    semantic_collection = client.get_or_create_collection(
        name=SEMANTIC_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    procedural_collection = client.get_or_create_collection(
        name=PROCEDURAL_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    runtime_collection = client.get_or_create_collection(
        name=RUNTIME_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    semantic_collection.upsert(
        ids=[SEMANTIC_PROFILE_ID],
        documents=[_prefs_doc_semantic(preferences)],
        metadatas=[
            {
                "user_name": str(preferences.get("user_name", "")),
                "user_email": str(preferences.get("user_email", "")),
                "user_email_aliases_json": _safe_json_text(preferences.get("user_email_aliases") or []),
                "vip_email_addresses_json": _safe_json_text(preferences.get("vip_email_addresses") or []),
                "preferred_location_json": _safe_json_text(preferences.get("preferred_location")),
                "preferred_location_text": str(preferences.get("preferred_location_text", "")),
                "identity_setup_completed": bool(preferences.get("identity_setup_completed", False)),
            }
        ],
    )

    procedural_collection.upsert(
        ids=[PROCEDURAL_RULES_ID],
        documents=[_prefs_doc_procedural(preferences)],
        metadatas=[
            {
                "temperature_unit": str(preferences.get("temperature_unit", "C")),
                "email_daily_digest_json": _safe_json_text(preferences.get("email_daily_digest")),
                "digest_preferences_summary": str(preferences.get("digest_preferences_summary", "")),
                "preferred_highlight_count": int(preferences.get("preferred_highlight_count") or 5),
            }
        ],
    )

    runtime_collection.upsert(
        ids=[RUNTIME_STATE_ID],
        documents=[_prefs_doc_runtime(preferences)],
        metadatas=[
            {
                "digest_feedback_json": _safe_json_text(preferences.get("digest_feedback") or []),
                "last_detected_location_json": _safe_json_text(preferences.get("last_detected_location")),
            }
        ],
    )


def _load_preferences_from_vector() -> dict:
    """Load semantic/procedural preference overlay from Chroma when available."""
    client = _get_chroma_client()
    if client is None:
        return {}

    overlay = {}
    try:
        semantic_collection = client.get_or_create_collection(
            name=SEMANTIC_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        result = semantic_collection.get(ids=[SEMANTIC_PROFILE_ID], include=["metadatas"])
        metadatas = result.get("metadatas") or []
        metadata = metadatas[0] if metadatas and isinstance(metadatas[0], dict) else {}
        if metadata:
            overlay.update(
                {
                    "user_name": str(metadata.get("user_name", "") or ""),
                    "user_email": str(metadata.get("user_email", "") or ""),
                    "user_email_aliases": _safe_parse_json_text(metadata.get("user_email_aliases_json", ""), []),
                    "vip_email_addresses": _safe_parse_json_text(metadata.get("vip_email_addresses_json", ""), []),
                    "preferred_location": _safe_parse_json_text(metadata.get("preferred_location_json", ""), None),
                    "preferred_location_text": str(metadata.get("preferred_location_text", "") or ""),
                    "identity_setup_completed": bool(metadata.get("identity_setup_completed", False)),
                }
            )
    except Exception:
        pass

    try:
        procedural_collection = client.get_or_create_collection(
            name=PROCEDURAL_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        result = procedural_collection.get(ids=[PROCEDURAL_RULES_ID], include=["metadatas"])
        metadatas = result.get("metadatas") or []
        metadata = metadatas[0] if metadatas and isinstance(metadatas[0], dict) else {}
        if metadata:
            overlay.update(
                {
                    "temperature_unit": str(metadata.get("temperature_unit", "C") or "C"),
                    "email_daily_digest": _safe_parse_json_text(metadata.get("email_daily_digest_json", ""), None),
                    "digest_preferences_summary": str(metadata.get("digest_preferences_summary", "") or ""),
                    "preferred_highlight_count": int(metadata.get("preferred_highlight_count") or 5),
                }
            )
    except Exception:
        pass

    try:
        runtime_collection = client.get_or_create_collection(
            name=RUNTIME_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        result = runtime_collection.get(ids=[RUNTIME_STATE_ID], include=["metadatas"])
        metadatas = result.get("metadatas") or []
        metadata = metadatas[0] if metadatas and isinstance(metadatas[0], dict) else {}
        if metadata:
            overlay.update(
                {
                    "digest_feedback": _safe_parse_json_text(metadata.get("digest_feedback_json", ""), []),
                    "last_detected_location": _safe_parse_json_text(
                        metadata.get("last_detected_location_json", ""),
                        None,
                    ),
                }
            )
    except Exception:
        pass

    return overlay


def _to_single_line(text: str) -> str:
    """Collapse all whitespace in a string into a single spaced line."""
    return re.sub(r"\s+", " ", text).strip()


def _format_location(location: dict) -> str:
    """Format a location dict into a readable city/region/country string."""
    return ", ".join(
        part for part in [location.get("city"), location.get("region"), location.get("country")] if part
    )


def _available_action_names() -> set:
    """Discover implemented action names from modules in actions/ directory."""
    names = set()
    if not ACTION_DIR.exists():
        return names
    for file_path in ACTION_DIR.glob("*_action.py"):
        stem = file_path.stem
        if stem == "__init__":
            continue
        names.add(stem[:-7])
    return names


def extract_feature_request(note: str) -> str:
    """Extract feature request token from free-text notes like 'add weather'."""
    compact = _to_single_line(note).lower()
    match = re.search(r"\b(?:add|include|enable|support)\s+([a-z_]+)\b", compact)
    if not match:
        return ""
    return match.group(1)


def is_resolved_feature_request(note: str) -> bool:
    """Return whether a feature-request note refers to an already implemented action."""
    feature = extract_feature_request(note)
    if not feature:
        return False
    return feature in _available_action_names()


def load_preferences() -> dict:
    """Load persisted user preferences with default keys when missing."""
    base = DEFAULT_PREFERENCES.copy()

    vector_overlay = _load_preferences_from_vector()
    if isinstance(vector_overlay, dict):
        base.update(vector_overlay)

    return base


def save_preferences(preferences: dict) -> None:
    """Persist preferences to vector storage."""
    try:
        _upsert_preferences_to_vector(preferences)
    except Exception:
        pass


def reset_all_preferences() -> dict:
    """Reset all persisted preferences to defaults and save them."""
    reset = DEFAULT_PREFERENCES.copy()
    save_preferences(reset)
    return reset


def reset_digest_preferences() -> dict:
    """Reset digest-only preferences while preserving identity/location/runtime settings."""
    current = load_preferences()
    reset = current.copy()
    for key in DIGEST_ONLY_DEFAULT_KEYS:
        reset[key] = DEFAULT_PREFERENCES[key]
    save_preferences(reset)
    return reset


def extract_temperature_unit_preference(note: str) -> str:
    """Extract preferred temperature unit from free-text feedback note."""
    lowered = note.lower()
    if "fahrenheit" in lowered or re.search(r"\buse\s+f\b|\bin\s+f\b|\bf\s+instead\s+of\s+c\b|\bis\s+f\b|\bset\s+to\s+f\b|\bprefer\s+f\b", lowered):
        return "F"
    if "celsius" in lowered or re.search(r"\buse\s+c\b|\bin\s+c\b|\bc\s+instead\s+of\s+f\b|\bis\s+c\b|\bset\s+to\s+c\b|\bprefer\s+c\b", lowered):
        return "C"
    return ""


def extract_location_preference_text(note: str) -> str:
    """Extract preferred location text from feedback note when user requests location changes."""
    compact = _to_single_line(note)
    patterns = [
        r"(?:fix|set|change|update)\s+(?:my\s+|the\s+)?location\s+to\s+(.+)$",
        r"(?:let'?s\s+)?fix\s+(?:my\s+|the\s+)?location\s+to\s+(.+)$",
        r"(?:my\s+)?location\s+should\s+be\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .")
    return ""


def extract_user_name_preference(note: str) -> str:
    """Extract user name from free-text preference notes."""
    compact = _to_single_line(note)
    patterns = [
        r"(?:my\s+name\s+is|i\s+am|i'm)\s+([A-Za-z][A-Za-z .'-]+)$",
        r"(?:call\s+me)\s+([A-Za-z][A-Za-z .'-]+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .")
    return ""


def extract_user_emails_preference(note: str) -> list:
    """Extract one or more user email addresses from free-text preference notes."""
    compact = _to_single_line(note)
    if not re.search(r"\b(my\s+email|my\s+emails|email\s+address|email\s+addresses|reach\s+me\s+at)\b", compact, flags=re.IGNORECASE):
        return []
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", compact, flags=re.IGNORECASE)
    deduped = []
    seen = set()
    for email in emails:
        lowered = email.lower()
        if lowered not in seen:
            seen.add(lowered)
            deduped.append(lowered)
    return deduped


def extract_vip_emails_preference(note: str) -> list:
    """Extract VIP email addresses from free-text preference notes."""
    compact = _to_single_line(note)
    if not re.search(
        r"\b(vip\s+email|vip\s+emails|important\s+email|important\s+emails|priority\s+email|priority\s+emails|treat\s+.+\s+as\s+vip)\b",
        compact,
        flags=re.IGNORECASE,
    ):
        return []
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", compact, flags=re.IGNORECASE)
    deduped = []
    seen = set()
    for email in emails:
        lowered = email.lower()
        if lowered not in seen:
            seen.add(lowered)
            deduped.append(lowered)
    return deduped


def extract_highlight_count_preference(note: str) -> int:
    """Extract preferred number of key highlights from free-text feedback note."""
    compact = _to_single_line(note)
    patterns = [
        r"show\s+(?:me\s+)?(?:up\s+to\s+)?(\w+|\d+)\s+(?:key\s+)?highlights",
        r"(?:key\s+)?highlights?\s+(?:count|number|limit)\s+(?:to|of|=)\s+(\w+|\d+)",
        r"(\w+|\d+)\s+(?:key\s+)?highlights?\s+(?:is\s+enough|please|only)",
        r"(?:increase|decrease|set|change)\s+(?:key\s+)?highlights?\s+to\s+(\w+|\d+)",
        r"(?:want|need|prefer)\s+(?:only\s+)?(\w+|\d+)\s+(?:key\s+)?highlights",
        r"(?:only|just)\s+(\w+|\d+)\s+(?:key\s+)?highlights",
        r"(?:key\s+)?highlights?\s+to\s+(\w+|\d+)",
        r"key\s+highlights?\s*[:\s]\s*(\w+|\d+)",
    ]
    word_to_int = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            raw = match.group(1).strip().lower()
            if raw.isdigit():
                count = int(raw)
            else:
                count = word_to_int.get(raw, 0)
            if 1 <= count <= 8:
                return count
    return 0


def get_user_identity(preferences: dict) -> dict:
    """Return normalized user identity fields from stored preferences."""
    primary_email = (preferences.get("user_email") or "").strip().lower()
    aliases = []
    seen = set()
    for email in preferences.get("user_email_aliases") or []:
        normalized = str(email).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            aliases.append(normalized)
    if primary_email and primary_email not in seen:
        aliases.insert(0, primary_email)
    return {
        "name": (preferences.get("user_name") or "").strip(),
        "email": primary_email,
        "emails": aliases,
    }


def get_vip_emails(preferences: dict) -> list:
    """Return normalized VIP email addresses from stored preferences."""
    deduped = []
    seen = set()
    for email in preferences.get("vip_email_addresses") or []:
        normalized = str(email).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def is_vip_email(email: str, preferences: dict) -> bool:
    """Return whether an email address is marked as VIP."""
    candidate = (email or "").strip().lower()
    if not candidate:
        return False
    return candidate in set(get_vip_emails(preferences))


def is_user_email(email: str, preferences: dict) -> bool:
    """Return whether an email address belongs to the configured user identity."""
    candidate = (email or "").strip().lower()
    if not candidate:
        return False
    identity = get_user_identity(preferences)
    return candidate in set(identity.get("emails") or [])


def resolve_preferred_location(location_text: str) -> dict:
    """Resolve user-entered preferred location text into a location profile dict."""
    query = _to_single_line(location_text)
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
        results = (response.json() or {}).get("results") or []
        if results:
            result = results[0]
            break

    if not result:
        raise ValueError(f"Could not resolve preferred location '{location_text}'.")

    return {
        "city": result.get("name") or "",
        "region": result.get("admin1") or "",
        "country": result.get("country") or "",
        "latlon": f"{result.get('latitude')},{result.get('longitude')}",
        "timezone": result.get("timezone") or "UTC",
    }


def apply_structured_preferences_from_feedback(
    preferences: dict,
    improvement_note: str,
    allow_override: bool = True,
) -> None:
    """Update explicit preference keys from free-text feedback notes."""
    if not improvement_note:
        return

    unit = extract_temperature_unit_preference(improvement_note)
    if unit and (allow_override or not preferences.get("temperature_unit")):
        preferences["temperature_unit"] = unit

    location_text = extract_location_preference_text(improvement_note)
    if location_text and (allow_override or not preferences.get("preferred_location_text")):
        preferences["preferred_location_text"] = location_text
        try:
            if allow_override or not preferences.get("preferred_location"):
                preferences["preferred_location"] = resolve_preferred_location(location_text)
        except (ValueError, requests.RequestException):
            # Keep the parsed text even if geocoding fails; user can refine later.
            pass

    user_name = extract_user_name_preference(improvement_note)
    if user_name and (allow_override or not preferences.get("user_name")):
        preferences["user_name"] = user_name

    user_emails = extract_user_emails_preference(improvement_note)
    if user_emails:
        existing = [str(email).strip().lower() for email in preferences.get("user_email_aliases") or [] if str(email).strip()]
        merged = []
        seen = set()
        for email in existing + user_emails:
            lowered = email.lower()
            if lowered not in seen:
                seen.add(lowered)
                merged.append(lowered)
        preferences["user_email_aliases"] = merged
        if allow_override or not preferences.get("user_email"):
            preferences["user_email"] = user_emails[0]

    vip_emails = extract_vip_emails_preference(improvement_note)
    if vip_emails:
        existing = [str(email).strip().lower() for email in preferences.get("vip_email_addresses") or [] if str(email).strip()]
        merged = []
        seen = set()
        for email in existing + vip_emails:
            lowered = email.lower()
            if lowered not in seen:
                seen.add(lowered)
                merged.append(lowered)
        preferences["vip_email_addresses"] = merged

    highlight_count = extract_highlight_count_preference(improvement_note)
    if highlight_count and (allow_override or not preferences.get("preferred_highlight_count")):
        preferences["preferred_highlight_count"] = highlight_count


def is_structured_preference_note(note: str) -> bool:
    """Return whether a free-text note maps to an explicit structured preference."""
    return bool(
        extract_temperature_unit_preference(note)
        or extract_location_preference_text(note)
        or extract_user_name_preference(note)
        or extract_user_emails_preference(note)
        or extract_vip_emails_preference(note)
        or extract_highlight_count_preference(note)
    )


def summarize_digest_preferences(preferences: dict) -> str:
    """Build a cumulative but deduplicated summary from feedback and structured preferences."""
    feedback_items = preferences.get("digest_feedback", [])
    if not feedback_items:
        return "No saved digest preferences yet."

    satisfaction_count = sum(1 for item in feedback_items if item.get("satisfied") is True)
    improvement_seen = set()
    improvement_notes = [
        _to_single_line(item.get("improvement_note", ""))
        for item in feedback_items
        if item.get("improvement_note") and _to_single_line(item.get("improvement_note", ""))
        and not is_structured_preference_note(_to_single_line(item.get("improvement_note", "")))
        and not is_resolved_feature_request(_to_single_line(item.get("improvement_note", "")))
        and not (
            _to_single_line(item.get("improvement_note", "")) in improvement_seen
            or improvement_seen.add(_to_single_line(item.get("improvement_note", "")))
        )
    ]
    summary_parts = [
        f"Digest feedback: {satisfaction_count}/{len(feedback_items)} marked satisfactory."
    ]
    email_daily_digest = preferences.get("email_daily_digest")
    if isinstance(email_daily_digest, bool):
        status = "enabled" if email_daily_digest else "disabled"
        summary_parts.append(f"Email daily digest delivery: {status}.")
    if preferences.get("temperature_unit") in {"C", "F"}:
        summary_parts.append(
            f"Temperature unit preference: {preferences['temperature_unit']}."
        )
    preferred = preferences.get("preferred_location")
    if isinstance(preferred, dict) and any(preferred.get(k) for k in ("city", "region", "country")):
        summary_parts.append(
            f"Preferred location: {_format_location(preferred)}."
        )
    identity = get_user_identity(preferences)
    if identity.get("name"):
        summary_parts.append(f"User name: {identity['name']}.")
    if identity.get("email"):
        alias_count = max(0, len(identity.get("emails") or []) - 1)
        alias_suffix = f" (+{alias_count} aliases)" if alias_count else ""
        summary_parts.append(f"User email: [user]{alias_suffix}.")
    vip_emails = get_vip_emails(preferences)
    if vip_emails:
        summary_parts.append("VIP emails: " + ", ".join("[VIP]" for _ in vip_emails) + ".")
    if improvement_notes:
        summary_parts.append(
            "Requested improvements history: " + " | ".join(improvement_notes)
        )
    return " ".join(summary_parts)


def backfill_structured_preferences_from_history(preferences: dict) -> bool:
    """Derive missing preference keys from feedback history without overriding current values."""
    before = json.dumps(
        {
            "temperature_unit": preferences.get("temperature_unit"),
            "preferred_location": preferences.get("preferred_location"),
            "preferred_location_text": preferences.get("preferred_location_text"),
            "user_name": preferences.get("user_name"),
            "user_email": preferences.get("user_email"),
            "user_email_aliases": preferences.get("user_email_aliases"),
            "vip_email_addresses": preferences.get("vip_email_addresses"),
        },
        sort_keys=True,
    )

    for item in preferences.get("digest_feedback", []):
        note = item.get("improvement_note", "")
        if note:
            apply_structured_preferences_from_feedback(preferences, note, allow_override=False)

    after = json.dumps(
        {
            "temperature_unit": preferences.get("temperature_unit"),
            "preferred_location": preferences.get("preferred_location"),
            "preferred_location_text": preferences.get("preferred_location_text"),
            "user_name": preferences.get("user_name"),
            "user_email": preferences.get("user_email"),
            "user_email_aliases": preferences.get("user_email_aliases"),
            "vip_email_addresses": preferences.get("vip_email_addresses"),
        },
        sort_keys=True,
    )
    return before != after
