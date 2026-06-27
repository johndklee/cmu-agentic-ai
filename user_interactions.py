"""User-facing setup and feedback workflows for the daily digest runtime."""

import re

from actions.email_action import send_email_action
from actions.location_action import current_location, format_location
from formatting import display_panel
from preferences import (
    get_user_identity,
    load_preferences,
)


DAILY_DIGEST_FROM_EMAIL = "agent@example.com"


def parse_email_list(raw_text: str) -> list:
    """Extract normalized email addresses from a free-form input string."""
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", raw_text or "", flags=re.IGNORECASE)
    ordered = []
    seen = set()
    for email in emails:
        lowered = email.lower()
        if lowered not in seen:
            seen.add(lowered)
            ordered.append(lowered)
    return ordered


def _extract_digest_title(answer: str) -> str:
    """Extract digest title from Rich markup answer content."""
    content = (answer or "").strip()
    if not content:
        return "Daily Digest"

    rich_title_match = re.search(r"\[bold\](.*?)\[/bold\]", content, flags=re.IGNORECASE | re.DOTALL)
    if rich_title_match:
        title = rich_title_match.group(1).strip()
        if title:
            return title

    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    if first_line:
        return first_line
    return "Daily Digest"


def maybe_send_digest_email(answer: str, subject: str = "", email_body: str = "") -> None:
    """Send digest email to the configured user when the preference is enabled."""
    preferences = load_preferences()
    if preferences.get("email_daily_digest") is not True:
        return

    identity = get_user_identity(preferences)
    user_email = (identity.get("email") or "").strip().lower()
    if not user_email:
        display_panel(
            "Digest email delivery is enabled, but no user email is configured."
            " Update your identity email to enable sending.",
            title="Digest Email",
            border_style="yellow",
        )
        return

    resolved_subject = (subject or "").strip() or _extract_digest_title(answer)
    resolved_body = email_body if email_body else answer
    send_status = send_email_action(
        to_email=user_email,
        from_email=DAILY_DIGEST_FROM_EMAIL,
        subject=resolved_subject,
        body=resolved_body,
    )
    border_style = "green" if send_status.startswith("Email sent.") else "red"
    display_panel(send_status, title="Digest Email", border_style=border_style)
