"""Deterministic key-highlights action with follow-up task creation."""

from datetime import datetime, timezone
import re

from actions.calendar_action import fetch_upcoming_events
from actions.email_action import fetch_recent_emails
from actions.tasks_action import ensure_follow_up_task, fetch_open_tasks


def _email_index(records: list) -> dict:
    """Index recent emails by every address appearing in the message headers."""
    index = {}
    for record in records:
        addresses = []
        seen = set()
        for address in record.get("from_addresses", []) + record.get("to_addresses", []) + record.get("cc_addresses", []):
            if address and address not in seen:
                seen.add(address)
                addresses.append(address)
        for address in addresses:
            index.setdefault(address, []).append(record)
    return index


def _requires_follow_up(attendee: dict, related_emails: list) -> bool:
    """Apply a conservative heuristic for when follow-up merits a task."""
    if attendee.get("is_vip"):
        return True
    if attendee.get("response_status") in {"needsAction", "tentative"}:
        return True
    if any(record.get("direction") == "sent_to_user" for record in related_emails):
        return True
    return False


def _priority_key(item: dict) -> tuple:
    """Sort VIP and follow-up-needed highlights first."""
    return (
        0 if item.get("is_vip") else 1,
        0 if item.get("requires_follow_up") else 1,
        item.get("event_start", ""),
        item.get("attendee_email", ""),
    )


def _parse_due_datetime(value: str):
    """Parse Google Tasks due timestamp into UTC datetime."""
    if not value:
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _task_intervention_highlights(tasks: list, horizon_days: int = 3) -> list:
    """Return overdue and due-soon task summaries requiring user intervention."""
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() + (horizon_days * 86400)
    overdue = []
    due_soon = []

    for task in tasks:
        due_dt = _parse_due_datetime(task.get("due", ""))
        if due_dt is None:
            continue
        due_ts = due_dt.timestamp()
        item = {
            "title": task.get("title") or "(untitled task)",
            "due": task.get("due") or due_dt.isoformat().replace("+00:00", "Z"),
            "owner_label": task.get("owner_label", "configured user"),
        }
        if due_ts < now.timestamp():
            overdue.append(item)
        elif due_ts <= cutoff:
            due_soon.append(item)

    overdue.sort(key=lambda item: item.get("due", ""))
    due_soon.sort(key=lambda item: item.get("due", ""))

    lines = []
    for item in overdue[:5]:
        lines.append(
            f"overdue task: {item['title']} (due {item['due']}; assigned_to: {item['owner_label']})"
        )
    for item in due_soon[:5]:
        lines.append(
            f"due soon task: {item['title']} (due {item['due']}; assigned_to: {item['owner_label']})"
        )
    return lines


def _parse_event_start_datetime(value: str):
    """Parse calendar event start into UTC datetime for near-term highlighting."""
    if not value:
        return None
    raw = value.strip()
    if "T" not in raw:
        try:
            dt = datetime.fromisoformat(raw + "T09:00:00+00:00")
        except ValueError:
            return None
        return dt.astimezone(timezone.utc)

    candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _near_term_event_highlights(events: list, horizon_hours: int = 24) -> list:
    """Return event summaries starting within the next N hours."""
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() + (horizon_hours * 3600)
    alerts = []

    for event in events:
        start_dt = _parse_event_start_datetime(event.get("start", ""))
        if start_dt is None:
            continue
        start_ts = start_dt.timestamp()
        if start_ts < now.timestamp() or start_ts > cutoff:
            continue
        alerts.append(
            f"upcoming event in next {horizon_hours}h: {event.get('summary', '(no title)')} @ {event.get('start', 'unknown')}"
        )

    return alerts[:5]


def _critical_unread_email_highlights(emails: list) -> list:
    """Return summaries for unread emails that likely need user intervention."""
    alerts = []
    urgency_pattern = re.compile(
        r"\b(urgent|asap|action needed|overdue|due today|deadline|payment due|final notice|immediately)\b",
        flags=re.IGNORECASE,
    )

    for record in emails:
        if not record.get("is_unread"):
            continue

        subject = record.get("subject", "(no subject)")
        body_preview = record.get("body_preview", "")
        is_vip = bool(record.get("vip_matches"))
        direction = record.get("direction", "unknown")
        seems_urgent = bool(urgency_pattern.search(subject) or urgency_pattern.search(body_preview))

        # Prioritize intervention if unread and either VIP-involved or urgency-signaled.
        if not (is_vip or seems_urgent):
            continue

        from_addresses = record.get("from_addresses", [])
        sender = from_addresses[0] if from_addresses else "unknown sender"
        tags = []
        if is_vip:
            tags.append("VIP")
        if seems_urgent:
            tags.append("urgent")
        tag_suffix = f" [{'|'.join(tags)}]" if tags else ""
        alerts.append(
            f"critical unread email: {subject} from {sender}{tag_suffix} ({direction}; date {record.get('date', 'unknown date')})"
        )

    return alerts[:5]


def run_key_highlights_action(max_events: int = 5, max_emails: int = 10) -> str:
    """Build key highlights from attendee/email overlap and create follow-up tasks when needed."""
    try:
        events = fetch_upcoming_events(max_items=max_events)
        emails = fetch_recent_emails(max_items=max_emails)
        tasklist_id, tasklist_title, existing_tasks = fetch_open_tasks(max_items=100)
    except Exception as err:
        return str(err)

    address_to_emails = _email_index(emails)
    critical_unread_alerts = _critical_unread_email_highlights(emails)
    near_term_event_alerts = _near_term_event_highlights(events, horizon_hours=24)
    highlights = []

    for event in events:
        for attendee in event.get("attendees", []):
            attendee_email = attendee.get("email", "")
            if not attendee_email or attendee_email == "unknown" or attendee.get("is_user"):
                continue
            related_emails = address_to_emails.get(attendee_email, [])
            if not related_emails:
                continue

            requires_follow_up = _requires_follow_up(attendee, related_emails)
            task_result = None
            if requires_follow_up:
                task_result = ensure_follow_up_task(
                    event_summary=event.get("summary", "(no title)"),
                    event_start=event.get("start", "unknown"),
                    attendee_email=attendee_email,
                    related_emails=related_emails,
                    tasklist_id=tasklist_id,
                    tasklist_title=tasklist_title,
                    existing_tasks=existing_tasks,
                )

            highlights.append(
                {
                    "event_summary": event.get("summary", "(no title)"),
                    "event_start": event.get("start", "unknown"),
                    "attendee_email": attendee_email,
                    "response_status": attendee.get("response_status", "needsAction"),
                    "is_vip": attendee.get("is_vip", False),
                    "requires_follow_up": requires_follow_up,
                    "related_emails": related_emails,
                    "task_result": task_result,
                }
            )

    if not highlights:
        intervention_lines = _task_intervention_highlights(existing_tasks, horizon_days=3)
        combined = critical_unread_alerts + intervention_lines + near_term_event_alerts
        if combined:
            return "Key highlights: " + " | ".join(combined)
        return (
            "Key highlights: no attendee/email overlaps found and no critical unread emails, "
            "overdue/due-soon tasks, or upcoming events in the next 24 hours."
        )

    rendered = []
    for item in sorted(highlights, key=_priority_key):
        vip_suffix = " [VIP]" if item.get("is_vip") else ""
        related_preview = ", ".join(
            f"{record.get('subject', '(no subject)')} ({record.get('direction', 'unknown')})"
            for record in item.get("related_emails", [])[:2]
        )
        line = (
            f"{item['attendee_email']}{vip_suffix} has recent email activity before {item['event_summary']} @ {item['event_start']} "
            f"[{item['response_status']}]"
        )
        if related_preview:
            line += f"; related emails: {related_preview}"
        if item.get("requires_follow_up"):
            task_result = item.get("task_result") or {}
            if task_result.get("status") == "created":
                line += f"; follow-up task created in {tasklist_title or 'Tasks'}: {task_result.get('title', '(untitled task)')}"
            elif task_result.get("status") == "existing":
                line += f"; existing follow-up task: {task_result.get('title', '(untitled task)')}"
            elif task_result.get("status") == "error":
                line += f"; follow-up task error: {task_result.get('message', 'unknown error')}"
        rendered.append(line)

    if critical_unread_alerts or near_term_event_alerts:
        rendered = critical_unread_alerts + near_term_event_alerts + rendered

    return "Key highlights: " + " | ".join(rendered)
