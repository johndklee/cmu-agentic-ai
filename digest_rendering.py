"""Channel-specific daily digest rendering from structured runtime observations."""

import json
import re

from formatting import strip_rich_markup, to_single_line


def _safe_json_loads(raw_text: str) -> dict:
    """Decode JSON text safely and return empty dict on parse failure."""
    if not raw_text:
        return {}
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_observation(text: str) -> str:
    """Normalize observation text for digest rendering."""
    plain = strip_rich_markup(text or "")
    return to_single_line(plain)


def _strip_known_prefix(section_name: str, text: str) -> str:
    """Remove action-specific prefixes to keep rendered section values concise."""
    value = (text or "").strip()
    if not value:
        return "Unknown"

    patterns = {
        "weather": r"^Current weather in .*?:\s*",
        "news": r"^Latest news in .*?:\s*",
        "calendar": r"^Upcoming calendar events:\s*",
        "tasks": r"^Tasks due today:\s*",
        "emails": r"^Inbox emails:\s*",
        "key_highlights": r"^Key highlights:\s*",
    }
    pattern = patterns.get(section_name)
    if pattern:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)

    return value or "Unknown"


def build_digest_payload(observations: dict) -> dict:
    """Build a canonical digest payload from observed action outputs."""
    observations = observations or {}
    digest_data = _safe_json_loads(observations.get("daily_digest", ""))
    location = digest_data.get("location") if isinstance(digest_data.get("location"), dict) else {}

    location_text = ", ".join(
        part for part in [location.get("city"), location.get("region"), location.get("country")] if part
    )
    if not location_text:
        location_text = _clean_observation(observations.get("location", "Unknown"))
        location_text = re.sub(r"^Current location is\s*", "", location_text, flags=re.IGNORECASE).rstrip(".")

    sections = {}
    for name in ["weather", "news", "calendar", "tasks", "emails", "key_highlights"]:
        raw_value = _clean_observation(observations.get(name, "Unknown"))
        sections[name] = _strip_known_prefix(name, raw_value)

    return {
        "title": (digest_data.get("title") or "Daily Digest").strip() or "Daily Digest",
        "location": location_text or "Unknown",
        "date": (digest_data.get("date") or "Unknown").strip() or "Unknown",
        "time": (digest_data.get("time") or "Unknown").strip() or "Unknown",
        "sections": sections,
    }


def _split_items(value: str, max_items: int = 8) -> list:
    """Split pipe-delimited section text into compact list items.

    Splits on ' | ' but skips splits that land inside [[url]] blocks,
    so URLs containing '|' are not broken.
    """
    if not value:
        return []
    # Split on ' | ' only when not inside [[ ]]
    parts = []
    current = []
    inside_url = False
    i = 0
    s = value
    while i < len(s):
        if s[i:i+2] == "[[":
            inside_url = True
            current.append(s[i])
        elif s[i:i+2] == "]]":
            inside_url = False
            current.append(s[i])
        elif not inside_url and s[i:i+3] == " | ":
            parts.append("".join(current).strip())
            current = []
            i += 2  # skip ' | ' (loop will add 1 more)
        else:
            current.append(s[i])
        i += 1
    if current:
        parts.append("".join(current).strip())
    candidates = [p for p in parts if p]
    if not candidates:
        return []
    if max_items <= 0:
        return candidates
    return candidates[:max_items]


def _split_calendar_items(value: str) -> list:
    """Split calendar section text into one entry per event using ;; delimiter."""
    if not value:
        return []
    parts = [p.strip() for p in value.split(";;") if p.strip()]
    return parts


def _split_email_items(value: str) -> list:
    """Split email section text into one entry per email record.

    Email records are joined with ' ;; ' (URL-safe delimiter).
    Falls back to ' | ' grouping for legacy data.
    """
    if not value:
        return []
    # Primary: emails are joined with ' ;; '
    if " ;; " in value:
        parts = [p.strip() for p in value.split(" ;; ") if p.strip()]
        return parts
    # Legacy: split on ' | ' and re-group by record start marker
    parts = _split_items(value, max_items=0)
    grouped = []
    for part in parts:
        lowered = part.lower()
        is_start = " - relation:" in lowered or lowered.startswith("relation:")
        if is_start or not grouped:
            grouped.append(part)
        else:
            grouped[-1] = f"{grouped[-1]} | {part}"
    return [p for p in grouped if p]


def _group_email_items(items: list) -> list:
    """Group email preview fragments under one bullet per top-level email."""
    grouped = []
    for item in items:
        lowered = item.lower()
        is_email_start = " - relation:" in lowered or lowered.startswith("relation:")
        if is_email_start or not grouped:
            grouped.append(item)
            continue
        grouped[-1] = f"{grouped[-1]} | {item}"
    return grouped


def _format_terminal_section_value(section_name: str, value: str) -> str:
    """Format a section value for terminal readability."""
    max_items = 0 if section_name in {"calendar", "emails"} else 8
    if section_name == "calendar":
        items = _split_calendar_items(value)
    else:
        items = _split_items(value, max_items=max_items)
    if section_name == "emails":
        items = _group_email_items(items)
    if len(items) <= 1:
        return value or "Unknown"
    return "\n" + "\n".join(f"  - {item}" for item in items)


def render_terminal_digest(payload: dict) -> str:
    """Render digest text for terminal display with readable section formatting."""
    sections = payload.get("sections", {})
    return (
        f"[bold]{payload.get('title', 'Daily Digest')}[/bold]\n\n"
        f"[bold cyan]Location:[/bold cyan] {payload.get('location', 'Unknown')}\n"
        f"[bold cyan]Date & Time:[/bold cyan] {payload.get('date', 'Unknown')} | {payload.get('time', 'Unknown')}\n"
        f"[bold cyan]Weather:[/bold cyan] {_format_terminal_section_value('weather', sections.get('weather', 'Unknown'))}\n"
        f"[bold cyan]Key Highlights:[/bold cyan] {_format_terminal_section_value('key_highlights', sections.get('key_highlights', 'Unknown'))}\n"
        f"[bold cyan]Tasks:[/bold cyan] {_format_terminal_section_value('tasks', sections.get('tasks', 'Unknown'))}\n"
        f"[bold cyan]Calendar:[/bold cyan] {_format_terminal_section_value('calendar', sections.get('calendar', 'Unknown'))}\n"
        f"[bold cyan]Emails:[/bold cyan] {_format_terminal_section_value('emails', sections.get('emails', 'Unknown'))}\n"
        f"[bold cyan]News:[/bold cyan] {_format_terminal_section_value('news', sections.get('news', 'Unknown'))}"
    )


def _format_email_section_value(section_name: str, value: str) -> str:
    """Format section values for email conversion with stable pipe delimiters."""
    max_items = 0 if section_name == "emails" else 8
    items = _split_items(value, max_items=max_items)
    if not items:
        return value or "Unknown"
    if len(items) == 1:
        return items[0]
    return " | ".join(items)


_URL_RE = re.compile(r"\s*\[\[(https?://[^\]]+)\]\]\s*$")


def _extract_url(text: str) -> tuple[str, str]:
    """Split '...text [[url]]' into (text, url). Returns (text, '') if no URL."""
    m = _URL_RE.search(text)
    if m:
        return text[:m.start()].strip(), m.group(1)
    return text.strip(), ""


_PRIORITY_RE = re.compile(r"\s+\((high|medium|low)\):", re.IGNORECASE)


def _link_label(text: str, url: str) -> str:
    """Extract the short clickable label from item text based on the URL type."""
    if not url:
        return text
    # Key highlights format: "Title (high): reason" — title is before the priority tag
    m = _PRIORITY_RE.search(text)
    if m:
        return text[:m.start()].strip()
    if "calendar.google.com" in url or "google.com/calendar" in url:
        # "Event Title @ date (organizer) — attendees" → "Event Title"
        return text.split(" @ ")[0].strip()
    if "tasks.google.com" in url:
        # "Task title (due ...)" → "Task title"
        return text.split(" (due")[0].split(" (")[0].strip()
    if "mail.google.com" in url:
        # "Subject - Relation: ..." → "Subject"
        return text.split(" - ")[0].strip()
    # News and others: full text is already the title
    return text


def _to_items(raw_list: list) -> list:
    """Convert a list of raw strings into [{text, label, url}] dicts for the frontend."""
    result = []
    for entry in raw_list:
        text, url = _extract_url(entry)
        item: dict = {"text": text}
        if url:
            item["url"] = url
            label = _link_label(text, url)
            if label != text:
                item["label"] = label
        result.append(item)
    return result


def render_json_digest(payload: dict) -> dict:
    """Render digest as a structured dict for API/React consumption."""
    sections = payload.get("sections", {})
    return {
        "title": payload.get("title", "Daily Digest"),
        "location": payload.get("location", "Unknown"),
        "date": payload.get("date", "Unknown"),
        "time": payload.get("time", "Unknown"),
        "sections": {
            name: _to_items(
                _split_calendar_items(sections.get(name, "Unknown"))
                if name == "calendar"
                else _split_email_items(sections.get(name, "Unknown"))
                if name == "emails"
                else _split_items(sections.get(name, "Unknown")) or [sections.get(name, "Unknown")]
            )
            for name in ["weather", "news", "calendar", "tasks", "emails", "key_highlights"]
        },
    }


def render_email_digest_markup(payload: dict) -> str:
    """Render digest markup optimized for downstream rich-markup-to-HTML conversion."""
    sections = payload.get("sections", {})
    return (
        f"[bold]{payload.get('title', 'Daily Digest')}[/bold]\n\n"
        f"Location: {payload.get('location', 'Unknown')}\n"
        f"Date & Time: {payload.get('date', 'Unknown')} | {payload.get('time', 'Unknown')}\n"
        f"Weather: {_format_email_section_value('weather', sections.get('weather', 'Unknown'))}\n"
        f"Key Highlights: {_format_email_section_value('key_highlights', sections.get('key_highlights', 'Unknown'))}\n"
        f"Tasks: {_format_email_section_value('tasks', sections.get('tasks', 'Unknown'))}\n"
        f"Calendar: {_format_email_section_value('calendar', sections.get('calendar', 'Unknown'))}\n"
        f"Emails: {_format_email_section_value('emails', sections.get('emails', 'Unknown'))}\n"
        f"News: {_format_email_section_value('news', sections.get('news', 'Unknown'))}"
    )
