"""Digest synthesis node for workflow controller."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from actions.daily_digest_action import build_digest_title
from actions.tasks_action import _format_due_date
from preferences import load_preferences
from workflow_state import WorkflowState


def _select_best_candidate(
    candidate_rankings: list[dict[str, Any]],
    scores: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select the highest-scoring candidate ranking."""
    if not candidate_rankings:
        return None

    by_id = {
        str(candidate.get("candidate_id") or ""): candidate
        for candidate in candidate_rankings
        if isinstance(candidate, dict)
    }
    ordered_scores = sorted(scores or [], key=lambda row: float(row.get("total", 0.0)), reverse=True)
    for row in ordered_scores:
        candidate_id = str(row.get("candidate_id") or "")
        if candidate_id in by_id:
            return by_id[candidate_id]

    return candidate_rankings[0] if candidate_rankings else None


def _build_digest_output(selected_ranking: dict[str, Any] | None, raw_fetched_data: dict[str, Any]) -> dict[str, Any]:
    """Build a compact digest artifact from selected ranking and fetched context."""
    location_data = raw_fetched_data.get("location") if isinstance(raw_fetched_data.get("location"), dict) else {}
    location = (location_data or {}).get("resolved_name") or "Unknown"
    timezone_name = (location_data or {}).get("timezone") or ""
    try:
        tz = ZoneInfo(timezone_name) if timezone_name else datetime.now().astimezone().tzinfo
    except ZoneInfoNotFoundError:
        tz = datetime.now().astimezone().tzinfo
    now = datetime.now(tz)
    date_text = now.strftime("%A, %B %d, %Y")
    time_text = now.strftime("%I:%M %p %Z").strip()

    def _join(items: list[str]) -> str:
        return " | ".join(part for part in items if part)

    weather = raw_fetched_data.get("weather") if isinstance(raw_fetched_data.get("weather"), dict) else {}
    weather_text = weather.get("description") or "Unknown"
    temperature = weather.get("temperature_c")
    if temperature is not None:
        prefs = load_preferences()
        use_f = (prefs.get("temperature_unit") or "C").upper() == "F"
        temp_val = (temperature * 9 / 5) + 32 if use_f else temperature
        unit_label = "F" if use_f else "C"
        weather_text = f"{weather_text}, {temp_val:.1f}{unit_label}"

    news_items = raw_fetched_data.get("news") if isinstance(raw_fetched_data.get("news"), list) else []
    news_text = _join(
        [
            (f"{item.get('title', '')} ({item.get('source', '')})" + (f" [[{item.get('url')}]]" if item.get('url') else "")).strip()
            for item in news_items
            if isinstance(item, dict) and item.get("title")
        ]
    ) or "Unknown"

    calendar_events = raw_fetched_data.get("calendar_events") if isinstance(raw_fetched_data.get("calendar_events"), list) else []
    calendar_text = " ;; ".join(
        (
            f"{event.get('summary', '(no title)')} @ {event.get('start', 'unknown')}"
            + (f" ({event.get('organizer')})" if event.get('organizer') else "")
            + (f" — {event.get('rendered_attendees')}" if event.get('rendered_attendees') else "")
            + (f" [[{event['url']}]]" if event.get('url') else "")
        ).strip()
        for event in calendar_events
        if isinstance(event, dict)
    ) or "Unknown"

    tasks = raw_fetched_data.get("tasks") if isinstance(raw_fetched_data.get("tasks"), list) else []
    tasks_text = _join(
        [
            f"{task.get('title', '(untitled task)')}" + (f" (due {_format_due_date(task['due'])})" if task.get('due') else "") + " [[https://tasks.google.com]]"
            for task in tasks
            if isinstance(task, dict)
        ]
    ) or "Unknown"

    emails = raw_fetched_data.get("emails") if isinstance(raw_fetched_data.get("emails"), list) else []
    emails_text = _join(
        [
            f"{email.get('subject', '(no subject)')} - Relation: {email.get('direction', 'unknown')} - From: {', '.join(email.get('from_addresses', []) or [])} - To: {', '.join(email.get('to_addresses', []) or [])} - Cc: {', '.join(email.get('cc_addresses', []) or [])} - Date: {email.get('date', 'unknown date')} - Body(3 lines, 280 chars max): {email.get('body_preview', '(no body preview)')}"
            + (f" [[{email['url']}]]" if email.get('url') else "")
            for email in emails
            if isinstance(email, dict)
        ]
    ) or "Unknown"

    item_labels: dict[str, str] = {}
    item_urls: dict[str, str] = {}
    for i, ev in enumerate(calendar_events, 1):
        key = f"calendar:{ev.get('id') or i}"
        item_labels[key] = ev.get("summary") or "(no title)"
        if ev.get("url"):
            item_urls[key] = ev["url"]
    for i, em in enumerate(emails, 1):
        key = f"emails:{em.get('id') or i}"
        item_labels[key] = em.get("subject") or "(no subject)"
        if em.get("url"):
            item_urls[key] = em["url"]
    for i, tk in enumerate(raw_fetched_data.get("tasks") or [], 1):
        key = f"tasks:{tk.get('id') or i}"
        item_labels[key] = tk.get("title") or "(untitled task)"
        item_urls[key] = "https://tasks.google.com"
    for i, nw in enumerate(raw_fetched_data.get("news") or [], 1):
        key = f"news:{i}"
        item_labels[key] = nw.get("title") or "(untitled)"
        if nw.get("url"):
            item_urls[key] = nw["url"]
    if isinstance(raw_fetched_data.get("weather"), dict):
        item_labels["weather:current"] = raw_fetched_data["weather"].get("description") or "Weather"

    highlight_count = int((load_preferences().get("preferred_highlight_count") or 5))
    ranking_entries = (selected_ranking or {}).get("ranking") or []
    highlights = []
    for entry in ranking_entries[:highlight_count]:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("item_id", "")
        label = item_labels.get(item_id) or item_id
        url_suffix = f" [[{item_urls[item_id]}]]" if item_id in item_urls else ""
        highlights.append(f"{label} ({entry.get('priority', '')}): {entry.get('reason', '')}{url_suffix}")

    return {
        "title": build_digest_title(load_preferences()),
        "location": location,
        "date": date_text,
        "time": time_text,
        "sections": {
            "weather": weather_text,
            "key_highlights": _join(highlights) or "Unknown",
            "tasks": tasks_text,
            "calendar": calendar_text,
            "emails": emails_text,
            "news": news_text,
        },
        "selected_candidate_id": str((selected_ranking or {}).get("candidate_id") or ""),
        "timezone": timezone_name,
    }


def _enforce_episodic_corrections(
    selected: dict[str, Any] | None,
    raw_fetched_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply deterministic corrections that the LLM must follow but may miss.

    Currently enforces:
    - Overdue tasks → forced to high priority and bubbled to top of ranking
    """
    if not selected:
        return selected

    from datetime import datetime, timezone as _tz

    tasks = raw_fetched_data.get("tasks") or []
    overdue_ids: set[str] = set()
    for i, task in enumerate(tasks, 1):
        due = (task.get("due") or "").strip()
        if not due:
            continue
        try:
            due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
            if due_dt < datetime.now(_tz.utc):
                overdue_ids.add(f"tasks:{task.get('id') or i}")
        except Exception:
            pass

    if not overdue_ids:
        return selected

    ranking = list(selected.get("ranking") or [])
    promoted, rest = [], []
    for entry in ranking:
        if not isinstance(entry, dict):
            rest.append(entry)
            continue
        if entry.get("item_id") in overdue_ids:
            entry = dict(entry)
            entry["priority"] = "high"
            if "overdue" not in (entry.get("reason") or "").lower():
                entry["reason"] = "Overdue — " + (entry.get("reason") or "past due date")
            promoted.append(entry)
        else:
            rest.append(entry)

    result = dict(selected)
    result["ranking"] = promoted + rest
    return result


def synthesize_digest(state: WorkflowState) -> WorkflowState:
    """Synthesize digest output from critic-selected candidate rankings."""
    next_state: WorkflowState = dict(state)
    raw_fetched_data = state.get("raw_fetched_data") if isinstance(state.get("raw_fetched_data"), dict) else {}
    candidate_rankings = state.get("candidate_rankings") if isinstance(state.get("candidate_rankings"), list) else []
    scores = state.get("scores") if isinstance(state.get("scores"), list) else []

    selected = _select_best_candidate(candidate_rankings, scores)
    selected = _enforce_episodic_corrections(selected, raw_fetched_data)
    next_state["selected_ranking"] = selected
    next_state["digest_output"] = _build_digest_output(selected, raw_fetched_data)
    return next_state
