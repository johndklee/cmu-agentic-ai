"""Google Calendar action helper."""

from datetime import datetime, timezone, timedelta
from email.utils import getaddresses

from googleapiclient.errors import HttpError

from actions.google_services import build_google_service, format_google_http_error
from preferences import is_user_email, is_vip_email, load_preferences


def _extract_email(raw_value: str) -> str:
    """Extract email address from a display-name/email string."""
    parsed = getaddresses([raw_value or ""])
    if parsed and parsed[0][1] and "@" in parsed[0][1]:
        return parsed[0][1]
    return ""


def _attendee_email(attendee: dict) -> str:
    """Return attendee email when available."""
    direct = (attendee.get("email") or "").strip()
    if direct:
        return direct
    fallback = _extract_email(attendee.get("displayName") or "")
    return fallback or "unknown"


def _tagged_email(email: str, preferences: dict) -> str:
    """Render one email with user/VIP tags."""
    tags = []
    if is_user_email(email, preferences):
        tags.append("user")
    if is_vip_email(email, preferences):
        tags.append("VIP")
    suffix = f" [{'|'.join(tags)}]" if tags else ""
    return f"{email}{suffix}"


def _format_event_attendees(event: dict, preferences: dict, max_per_group: int = 3) -> str:
    """Render attendees by response status for one event."""
    attendees = event.get("attendees") or []
    if not attendees:
        return "no attendees listed"

    grouped = {
        "accepted": [],
        "tentative": [],
        "needsAction": [],
        "declined": [],
    }

    for attendee in attendees:
        label = _tagged_email(_attendee_email(attendee), preferences)
        status = attendee.get("responseStatus") or "needsAction"
        if status not in grouped:
            status = "needsAction"
        grouped[status].append(label)

    parts = []
    order = [
        ("accepted", "attending"),
        ("tentative", "tentative"),
        ("needsAction", "invited"),
        ("declined", "declined"),
    ]
    for status_key, label in order:
        names = grouped.get(status_key) or []
        if not names:
            continue
        shown = ", ".join(names[:max_per_group])
        extra_count = len(names) - max_per_group
        if extra_count > 0:
            shown += f", +{extra_count} more"
        parts.append(f"{label}: {shown}")

    return "; ".join(parts) if parts else "no attendees listed"


def fetch_upcoming_events(max_items: int = 5) -> list:
    """Fetch upcoming calendar events as structured records."""
    preferences = load_preferences()
    service = build_google_service("calendar", "v3")
    now_utc = datetime.now(timezone.utc)
    one_month_ahead = (now_utc + timedelta(days=31)).isoformat()
    result = service.events().list(
        calendarId="primary",
        timeMin=now_utc.isoformat(),
        timeMax=one_month_ahead,
        maxResults=max_items,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    records = []
    for event in result.get("items", []):
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date") or "unknown"
        summary = event.get("summary") or "(no title)"
        organizer_raw = event.get("organizer", {}).get("email") or ""
        organizer = _extract_email(organizer_raw) or organizer_raw or "unknown"
        attendees = []
        for attendee in event.get("attendees") or []:
            email = _attendee_email(attendee)
            attendees.append(
                {
                    "email": email,
                    "response_status": attendee.get("responseStatus") or "needsAction",
                    "is_user": is_user_email(email, preferences),
                    "is_vip": is_vip_email(email, preferences),
                }
            )
        records.append(
            {
                "id": event.get("id", ""),
                "summary": summary,
                "start": start,
                "organizer": organizer,
                "organizer_relation": "organized_by_user" if is_user_email(organizer, preferences) else "organized_by_other",
                "organizer_is_vip": is_vip_email(organizer, preferences),
                "attendees": attendees,
                "rendered_attendees": _format_event_attendees(event, preferences),
                "url": event.get("htmlLink") or "",
            }
        )
    return records


def run_calendar_action(max_items: int = 5) -> str:
    """Fetch upcoming events from the primary Google Calendar."""
    try:
        preferences = load_preferences()
        events = fetch_upcoming_events(max_items=max_items)
    except HttpError as err:
        return format_google_http_error("Calendar", err)

    if not events:
        return "Upcoming calendar events: none found."

    rendered = []
    for event in events:
        start = event["start"]
        summary = event["summary"]
        organizer = event["organizer"]
        organizer_relation = event["organizer_relation"]
        organizer_vip = "VIP" if event["organizer_is_vip"] else "non_vip"
        attendee_text = event["rendered_attendees"]
        rendered.append(
            f"{summary} @ {start} ({_tagged_email(organizer, preferences)}) — {attendee_text}"
        )

    return "Upcoming calendar events: " + " ;; ".join(rendered)
