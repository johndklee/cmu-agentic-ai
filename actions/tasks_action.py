"""Google Tasks action helper."""

import re
from datetime import datetime, timedelta, timezone

from googleapiclient.errors import HttpError

from actions.google_services import build_google_service, format_google_http_error
from preferences import get_user_identity, load_preferences


def _format_due_date(due: str) -> str:
    """Format a Google Tasks RFC 3339 due date into a locale-friendly date string."""
    try:
        dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
        prefs = load_preferences()
        tz_name = prefs.get("timezone") or ""
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(tz_name) if tz_name else datetime.now().astimezone().tzinfo
            dt = dt.astimezone(tz)
        except Exception:
            dt = dt.astimezone()
        return dt.strftime("%b %-d, %Y")
    except Exception:
        return due


def _primary_tasklist(service) -> tuple:
    """Return primary task list id and title."""
    lists_result = service.tasklists().list(maxResults=10).execute()
    tasklists = lists_result.get("items", [])
    if not tasklists:
        return "", ""
    primary_list = tasklists[0]
    return primary_list.get("id", ""), primary_list.get("title") or "Tasks"


def fetch_open_tasks(max_items: int = 5) -> tuple:
    """Fetch open tasks as structured records."""
    preferences = load_preferences()
    service = build_google_service("tasks", "v1")
    list_id, list_title = _primary_tasklist(service)
    if not list_id:
        return "", "", []

    tasks_result = service.tasks().list(
        tasklist=list_id,
        showCompleted=False,
        showHidden=False,
        maxResults=max_items,
    ).execute()
    identity = get_user_identity(preferences)
    owner_label = identity.get("email") or identity.get("name") or "configured user"
    tasks = []
    for task in tasks_result.get("items", []):
        tasks.append(
            {
                "id": task.get("id", ""),
                "title": task.get("title") or "(untitled task)",
                "notes": task.get("notes") or "",
                "due": task.get("due"),
                "owner_label": owner_label,
            }
        )
    return list_id, list_title, tasks


def _follow_up_key(event_summary: str, attendee_email: str) -> str:
    """Build a stable marker used to dedupe auto-created follow-up tasks."""
    normalized_summary = re.sub(r"\s+", " ", (event_summary or "").strip().lower())
    normalized_attendee = (attendee_email or "").strip().lower()
    return f"auto_follow_up_key: {normalized_summary}::{normalized_attendee}"


def _due_before_event(start_value: str) -> str:
    """Return an RFC3339 due timestamp before the event starts."""
    raw = (start_value or "").strip()
    if not raw or raw == "unknown":
        return ""
    if "T" not in raw:
        event_date = datetime.fromisoformat(raw).date()
        due_dt = datetime.combine(event_date - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        due_dt = due_dt.replace(hour=9)
        return due_dt.isoformat(timespec="seconds").replace("+00:00", "Z")

    normalized = raw.replace("Z", "+00:00")
    event_dt = datetime.fromisoformat(normalized)
    if event_dt.tzinfo is None:
        event_dt = event_dt.replace(tzinfo=timezone.utc)
    due_dt = (event_dt - timedelta(days=1)).astimezone(timezone.utc)
    return due_dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_follow_up_task(
    event_summary: str,
    event_start: str,
    attendee_email: str,
    related_emails: list,
    tasklist_id: str = "",
    tasklist_title: str = "",
    existing_tasks: list = None,
) -> dict:
    """Create a follow-up task unless one already exists for the same event/attendee."""
    if existing_tasks is None or not tasklist_id:
        tasklist_id, tasklist_title, existing_tasks = fetch_open_tasks(max_items=100)

    if not tasklist_id:
        return {"status": "error", "message": "Open tasks: no task lists found."}

    marker = _follow_up_key(event_summary, attendee_email)
    for task in existing_tasks:
        if marker in (task.get("notes") or ""):
            return {"status": "existing", "title": task.get("title", "(untitled task)")}

    bullet_lines = []
    for email in related_emails[:3]:
        bullet_lines.append(
            f"- {email.get('date', 'unknown date')}: {email.get('subject', '(no subject)')} [{email.get('direction', 'unknown')}]"
        )
    task_title = f"Follow up with [VIP] before {event_summary}"
    notes = (
        f"Follow-up needed before upcoming event.\n"
        f"Event: {event_summary}\n"
        f"Event start: {event_start}\n"
        f"Attendee: [VIP]\n"
        f"Recent related emails:\n" + ("\n".join(bullet_lines) if bullet_lines else "- none") + f"\n{marker}"
    )
    task_body = {"title": task_title, "notes": notes}
    due_value = _due_before_event(event_start)
    if due_value:
        task_body["due"] = due_value

    try:
        service = build_google_service("tasks", "v1")
        created = service.tasks().insert(tasklist=tasklist_id, body=task_body).execute()
    except HttpError as err:
        return {"status": "error", "message": format_google_http_error("Tasks", err)}

    created_task = {
        "id": created.get("id", ""),
        "title": created.get("title") or task_title,
        "notes": created.get("notes") or notes,
        "due": created.get("due") or due_value,
    }
    existing_tasks.append(created_task)
    return {"status": "created", "title": created_task["title"], "due": created_task.get("due") or ""}


def run_tasks_action(max_items: int = 5) -> str:
    """Fetch open tasks from the first available Google task list."""
    try:
        _tasklist_id, list_title, tasks = fetch_open_tasks(max_items=max_items)
    except HttpError as err:
        return format_google_http_error("Tasks", err)

    if not tasks:
        return f"Open tasks ({list_title}): none found."

    rendered = []
    for task in tasks:
        title = task.get("title") or "(untitled task)"
        due = task.get("due")
        due_str = _format_due_date(due) if due else None
        relation = f"assigned_to: {task.get('owner_label', 'configured user')}"
        rendered.append(f"{title}" + (f" (due {due_str})" if due_str else "") + f" [{relation}]")

    return f"Open tasks ({list_title}): " + " | ".join(rendered)
