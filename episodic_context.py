"""Digest run context helpers used for episodic memory extraction and retrieval queries."""

import re

from actions.location_action import current_location, format_location
from preferences import get_user_identity, get_vip_emails


DIGEST_RUN_CONTEXT = {
    "by_action": {},
    "ordered_actions": [],
}


def reset_digest_run_context() -> None:
    """Clear per-run digest observations before a new ReAct session."""
    DIGEST_RUN_CONTEXT["by_action"] = {}
    DIGEST_RUN_CONTEXT["ordered_actions"] = []


def remember_digest_observation(action_name: str, observation: str) -> None:
    """Store latest observation text per action for episodic correction logging."""
    if not action_name:
        return
    text = (observation or "").strip()
    if not text:
        return
    DIGEST_RUN_CONTEXT["by_action"][action_name] = text
    DIGEST_RUN_CONTEXT["ordered_actions"].append(action_name)


def get_digest_observations_snapshot() -> dict:
    """Return a shallow copy of current per-action observations."""
    return dict(DIGEST_RUN_CONTEXT.get("by_action", {}))


def _first_email(text: str) -> str:
    """Extract the first email address from free-form text."""
    match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text or "", flags=re.IGNORECASE)
    return (match.group(0).lower() if match else "")


def extract_sender_email_for_episode(improvement_note: str) -> str:
    """Infer sender email from feedback note, key highlights, or email observation."""
    note_email = _first_email(improvement_note)
    if note_email:
        return note_email

    key_highlights_obs = DIGEST_RUN_CONTEXT["by_action"].get("key_highlights", "")
    highlights_email = _first_email(key_highlights_obs)
    if highlights_email:
        return highlights_email

    emails_obs = DIGEST_RUN_CONTEXT["by_action"].get("emails", "")
    return _first_email(emails_obs)


def extract_meeting_context_for_episode() -> str:
    """Infer meeting context from key highlights or calendar output."""
    key_highlights_obs = DIGEST_RUN_CONTEXT["by_action"].get("key_highlights", "")
    highlights_match = re.search(r"before\s+(.+?)\s+@\s+([^;|]+)", key_highlights_obs, flags=re.IGNORECASE)
    if highlights_match:
        return f"{highlights_match.group(1).strip()} @ {highlights_match.group(2).strip()}"

    calendar_obs = DIGEST_RUN_CONTEXT["by_action"].get("calendar", "")
    calendar_match = re.search(r"Upcoming calendar events:\s*([^@|]+)\s+@\s+([^|]+)", calendar_obs)
    if calendar_match:
        return f"{calendar_match.group(1).strip()} @ {calendar_match.group(2).strip()}"

    return ""


def extract_original_ranking_for_episode(improvement_note: str) -> str:
    """Infer the ranking correction requested by user feedback."""
    lowered = (improvement_note or "").lower()
    if re.search(r"\b(top|first|1st)\b", lowered):
        return "top"
    if re.search(r"\b(second|2nd)\b", lowered):
        return "second"
    if re.search(r"\b(third|3rd)\b", lowered):
        return "third"
    if re.search(r"\b(bottom|last)\b", lowered):
        return "bottom"

    section_order = [
        action
        for action in DIGEST_RUN_CONTEXT.get("ordered_actions", [])
        if action in {"key_highlights", "emails", "calendar", "tasks", "news", "weather"}
    ]
    if section_order:
        deduped = []
        seen = set()
        for action in section_order:
            if action not in seen:
                seen.add(action)
                deduped.append(action)
        return "section_order:" + ">".join(deduped)

    return "unknown"


def _extract_unique_emails(text: str, max_items: int = 8) -> list:
    """Extract deduplicated email addresses from free-form observation text."""
    matches = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text or "", flags=re.IGNORECASE)
    ordered = []
    seen = set()
    for email in matches:
        lowered = email.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(lowered)
        if len(ordered) >= max_items:
            break
    return ordered


def _extract_event_snippets(text: str, max_items: int = 4) -> list:
    """Extract compact event snippets from calendar/key-highlights observations."""
    snippets = []
    if not text:
        return snippets

    for match in re.finditer(r"before\s+(.+?)\s+@\s+([^;|]+)", text, flags=re.IGNORECASE):
        snippets.append(f"{match.group(1).strip()} @ {match.group(2).strip()}")
        if len(snippets) >= max_items:
            return snippets

    for match in re.finditer(r"(?:^|\|)\s*([^@|]{3,80})\s+@\s+([^|]{3,80})", text):
        candidate = f"{match.group(1).strip()} @ {match.group(2).strip()}"
        if candidate not in snippets:
            snippets.append(candidate)
        if len(snippets) >= max_items:
            break
    return snippets


def _extract_urgency_markers() -> list:
    """Infer urgency signals from current run observations."""
    corpus = " ".join(
        DIGEST_RUN_CONTEXT["by_action"].get(name, "")
        for name in ("key_highlights", "calendar", "emails", "tasks")
    ).lower()
    markers = []
    for token in [
        "vip",
        "needsaction",
        "tentative",
        "follow-up",
        "follow up",
        "due",
        "urgent",
        "back-to-back",
    ]:
        if token in corpus:
            markers.append(token)
    return markers


def select_retrieval_correction_type() -> str:
    """Choose correction-type scope for retrieval based on current run signals."""
    corpus = " ".join(
        DIGEST_RUN_CONTEXT["by_action"].get(name, "")
        for name in ("key_highlights", "calendar", "emails", "tasks")
    ).lower()

    if any(token in corpus for token in ["vip", "needsaction", "tentative", "follow-up", "follow up", "urgent"]):
        return "priority_override"

    if any(token in corpus for token in ["missing", "missed", "left out", "didn't include", "did not include"]):
        return "missed_item"

    if any(token in corpus for token in ["irrelevant", "noise", "too much", "spam", "remove"]):
        return "irrelevant_item"

    if any(token in corpus for token in ["order", "format", "style", "layout", "first", "top"]):
        return "formatting_feedback"

    if any(token in corpus for token in ["location", "weather", "temperature", "topic", "sender", "email"]):
        return "preference_update"

    return ""


def build_episodic_query_context(preferences: dict) -> str:
    """Build retrieval query from current-run signals and user profile."""
    identity = get_user_identity(preferences)
    vip_emails = get_vip_emails(preferences)
    vip_label = ", ".join(vip_emails[:5]) if vip_emails else "none"
    user_label = identity.get("email") or identity.get("name") or "unknown"
    key_highlights_obs = DIGEST_RUN_CONTEXT["by_action"].get("key_highlights", "")
    calendar_obs = DIGEST_RUN_CONTEXT["by_action"].get("calendar", "")
    emails_obs = DIGEST_RUN_CONTEXT["by_action"].get("emails", "")

    attendees = _extract_unique_emails(key_highlights_obs + " " + calendar_obs, max_items=8)
    senders = _extract_unique_emails(emails_obs, max_items=8)
    events = _extract_event_snippets(key_highlights_obs + " | " + calendar_obs, max_items=4)
    urgency = _extract_urgency_markers()

    attendees_label = ", ".join(attendees) if attendees else "none"
    senders_label = ", ".join(senders) if senders else "none"
    events_label = " | ".join(events) if events else "none"
    urgency_label = ", ".join(urgency) if urgency else "none"
    return (
        "daily digest correction retrieval; "
        f"location={format_location(current_location())}; "
        f"user={user_label}; "
        f"vip_emails={vip_label}; "
        f"today_attendees={attendees_label}; "
        f"recent_senders={senders_label}; "
        f"event_context={events_label}; "
        f"urgency_signals={urgency_label}; "
        "focus=priority ordering missed and irrelevant items"
    )
