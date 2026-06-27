"""Gmail inbox action helper."""

import base64
import html
import re
from email.message import EmailMessage
from email.utils import getaddresses

from googleapiclient.errors import HttpError

from actions.google_services import build_google_service, format_google_http_error
from actions.news_action import get_latest_news_records
from formatting import strip_rich_markup
from preferences import is_user_email, is_vip_email, load_preferences


def _header_map(headers):
    return {h.get("name", "").lower(): h.get("value", "") for h in headers or []}


def _extract_addresses(value: str) -> list:
    """Parse one header value into plain email addresses."""
    parsed = getaddresses([value or ""])
    addresses = [addr for _, addr in parsed if addr and "@" in addr]
    return addresses


def _format_address_list(value: str) -> str:
    """Render normalized email addresses for output."""
    addresses = _extract_addresses(value)
    return ", ".join(addresses) if addresses else "(none)"


def _format_address_list_with_tags(addresses: list, preferences: dict) -> str:
    """Render email addresses with VIP/user tags for stronger raw observations."""
    if not addresses:
        return "(none)"
    rendered = []
    for address in addresses:
        tags = []
        if is_user_email(address, preferences):
            tags.append("user")
        if is_vip_email(address, preferences):
            tags.append("VIP")
        suffix = f" [{'|'.join(tags)}]" if tags else ""
        rendered.append(f"{address}{suffix}")
    return ", ".join(rendered)


def _message_vip_relation(from_addresses: list, to_addresses: list, cc_addresses: list, preferences: dict) -> str:
    """Summarize whether a message involves any VIP address."""
    all_addresses = from_addresses + to_addresses + cc_addresses
    vip_addresses = [address for address in all_addresses if is_vip_email(address, preferences)]
    if not vip_addresses:
        return "no_vip_match"
    ordered = []
    seen = set()
    for address in vip_addresses:
        if address not in seen:
            seen.add(address)
            ordered.append(address)
    return "vip_match: " + ", ".join(ordered)


def _email_direction(from_addresses: list, to_addresses: list, cc_addresses: list, preferences: dict) -> str:
    """Describe whether the configured user sent or received the message."""
    if any(is_user_email(addr, preferences) for addr in from_addresses):
        return "sent_by_user"
    if any(is_user_email(addr, preferences) for addr in to_addresses + cc_addresses):
        return "sent_to_user"
    return "user_relation_unknown"


def _decode_body_data(data: str) -> str:
    """Decode base64url body data from Gmail API into text."""
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode((data + padding).encode("utf-8"))
    return decoded.decode("utf-8", errors="replace")


def _payload_text(payload: dict) -> str:
    """Extract readable text from a Gmail payload tree."""
    mime_type = payload.get("mimeType", "")
    body_data = (payload.get("body") or {}).get("data", "")
    parts = payload.get("parts") or []

    if mime_type == "text/plain" and body_data:
        return html.unescape(_decode_body_data(body_data))

    for part in parts:
        text = _payload_text(part)
        if text:
            return text

    if mime_type == "text/html" and body_data:
        html_text = _decode_body_data(body_data)
        plain = re.sub(r"<[^>]+>", " ", html_text)
        plain = html.unescape(plain)
        plain = re.sub(r"\s+", " ", plain).strip()
        return plain

    if body_data:
        return _decode_body_data(body_data)

    return ""


def _clean_body_text(text: str) -> str:
    """Strip URLs, HTML remnants, and email boilerplate noise from body text."""
    # Remove bare URLs (http/https) including surrounding angle brackets
    text = re.sub(r"<?\bhttps?://\S+>?", "", text)
    # Remove mailto: links
    text = re.sub(r"<?\bmailto:\S+>?", "", text)
    # Remove residual HTML entities not caught by html.unescape (e.g. &#160;)
    text = re.sub(r"&#?\w+;", " ", text)
    # Remove lines that are purely punctuation / symbols / whitespace after above
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Drop lines where fewer than 30% of characters are alphanumeric (URL/code noise)
        alnum = sum(1 for c in stripped if c.isalnum())
        if alnum == 0 or (len(stripped) > 10 and alnum / len(stripped) < 0.30):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _first_body_lines(payload: dict, max_lines: int = 3, max_chars: int = 280) -> str:
    """Return a compact preview of the first N non-empty body lines."""
    text = _payload_text(payload)
    if not text:
        return "(no body preview)"

    text = _clean_body_text(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "(no body preview)"

    preview_lines = lines[:max_lines]
    preview = " || ".join(preview_lines)
    if len(preview) > max_chars:
        return preview[: max_chars - 3].rstrip() + "..."
    return preview


def fetch_recent_emails(max_items: int = 5) -> list:
    """Fetch recent inbox emails as structured records."""
    preferences = load_preferences()
    service = build_google_service("gmail", "v1")
    list_result = service.users().messages().list(
        userId="me",
        labelIds=["INBOX"],
        maxResults=max_items,
    ).execute()
    messages = list_result.get("messages", [])

    records = []
    for item in messages:
        msg_id = item.get("id")
        if not msg_id:
            continue
        msg = service.users().messages().get(
            userId="me",
            id=msg_id,
            format="full",
            metadataHeaders=["From", "To", "Cc", "Subject", "Date"],
        ).execute()
        payload = msg.get("payload", {})
        headers = _header_map(payload.get("headers", []))
        from_addresses = _extract_addresses(headers.get("from", ""))
        to_addresses = _extract_addresses(headers.get("to", ""))
        cc_addresses = _extract_addresses(headers.get("cc", ""))
        direction = _email_direction(from_addresses, to_addresses, cc_addresses, preferences)
        vip_matches = []
        seen_vips = set()
        for address in from_addresses + to_addresses + cc_addresses:
            if is_vip_email(address, preferences) and address not in seen_vips:
                seen_vips.add(address)
                vip_matches.append(address)
        records.append(
            {
                "id": msg_id,
                "url": f"https://mail.google.com/mail/u/0/#inbox/{msg_id}",
                "label_ids": msg.get("labelIds", []) or [],
                "is_unread": "UNREAD" in (msg.get("labelIds", []) or []),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", "unknown date"),
                "from_addresses": from_addresses,
                "to_addresses": to_addresses,
                "cc_addresses": cc_addresses,
                "direction": direction,
                "vip_matches": vip_matches,
                "body_preview": _first_body_lines(payload, max_lines=3, max_chars=280),
            }
        )
    return records


def run_email_action(max_items: int = 5) -> str:
    """Fetch recent inbox emails from Gmail."""
    try:
        preferences = load_preferences()
        records = fetch_recent_emails(max_items=max_items)
        if not records:
            return "Inbox emails: none found."

        rendered = []
        for record in records:
            from_addresses = record["from_addresses"]
            to_addresses = record["to_addresses"]
            cc_addresses = record["cc_addresses"]
            sender = _format_address_list_with_tags(from_addresses, preferences)
            to_value = _format_address_list_with_tags(to_addresses, preferences)
            cc_value = _format_address_list_with_tags(cc_addresses, preferences)
            subject = record["subject"]
            date = record["date"]
            preview = record["body_preview"]
            direction = record["direction"]
            vip_relation = _message_vip_relation(from_addresses, to_addresses, cc_addresses, preferences)
            rendered.append(
                    f"{subject} - Relation: {direction} - VIP: {vip_relation} - From: {sender} - To: {to_value} - Cc: {cc_value} - Date: {date} - Body(3 lines, 280 chars max): {preview}"
            )

        if not rendered:
            return "Inbox emails: none found."

        return "Inbox emails: " + " ;; ".join(rendered)
    except HttpError as err:
        return format_google_http_error("Gmail", err)


def send_email_action(to_email: str, subject: str, body: str, from_email: str = "") -> str:
    """Send an email with Gmail API and return a compact status message."""
    try:
        service = build_google_service("gmail", "v1")
        message = EmailMessage()
        message["To"] = (to_email or "").strip()
        if from_email:
            message["From"] = f"Daily Digest Agent <{from_email.strip()}>"
        message["Subject"] = (subject or "Daily Digest").strip() or "Daily Digest"
        plain_text = strip_rich_markup(body or "")
        html_body = _rich_markup_to_html(body or "")
        message.set_content(plain_text)
        message.add_alternative(html_body, subtype="html")

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        response = service.users().messages().send(
            userId="me",
            body={"raw": raw_message},
        ).execute()
        message_id = response.get("id", "unknown")

        # Gmail may rewrite From unless the alias is configured and verified in Send As.
        sent_message = service.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From"],
        ).execute()
        sent_headers = _header_map((sent_message.get("payload") or {}).get("headers") or [])
        actual_from_header = sent_headers.get("from", "")
        actual_from_addresses = _extract_addresses(actual_from_header)
        actual_from_email = (actual_from_addresses[0].strip().lower() if actual_from_addresses else "")
        requested_from_email = (from_email or "").strip().lower()

        if requested_from_email and actual_from_email and actual_from_email != requested_from_email:
            return (
                f"Email sent. Gmail message id: {message_id}. "
                f"Gmail rewrote From to '{actual_from_header}'. "
                f"To send as '{requested_from_email}', add and verify it in Gmail Settings > Accounts and Import > Send mail as."
            )

        if actual_from_header and not actual_from_header.lower().startswith("daily digest agent"):
            return (
                f"Email sent. Gmail message id: {message_id}. "
                f"From was '{actual_from_header}' instead of 'Daily Digest Agent'. "
                "Set the Send As display name for that alias in Gmail settings."
            )

        return f"Email sent. Gmail message id: {message_id}."
    except HttpError as err:
        return format_google_http_error("Gmail", err)


def _rich_markup_to_html(text: str) -> str:
    """Convert Rich-markup digest text into structured HTML suitable for email clients."""
    section_order = [
        "location",
        "date & time",
        "date",
        "time",
        "weather",
        "news",
        "calendar",
        "tasks",
        "emails",
        "key highlights",
        "note",
    ]
    section_lookup = {name.lower(): name.title() for name in section_order}

    lines = (text or "").splitlines()
    title = "Daily Digest"
    intro_lines = []
    sections = []
    current_section_index = -1

    for raw_line in lines:
        if not raw_line.strip():
            continue
        # Preserve [[url]] news links before stripping markup — convert to "- URL: <url>"
        raw_line = re.sub(r"\[\[(https?://[^\]]+)\]\]", r"- URL: \1", raw_line)
        plain_line = strip_rich_markup(raw_line).strip()
        if not plain_line:
            continue

        if title == "Daily Digest":
            rich_title_match = re.search(r"\[bold\](.*?)\[/bold\]", raw_line, flags=re.IGNORECASE | re.DOTALL)
            if rich_title_match and strip_rich_markup(rich_title_match.group(1)).strip():
                title = strip_rich_markup(rich_title_match.group(1)).strip()
                continue
            if plain_line.lower().startswith("daily digest"):
                title = plain_line
                continue

        section_match = re.match(r"^([A-Za-z][A-Za-z &/]+):\s*(.*)$", plain_line)
        if section_match:
            key = section_match.group(1).strip().lower()
            value = section_match.group(2).strip()
            if key in section_lookup:
                sections.append((section_lookup[key], value))
                current_section_index = len(sections) - 1
                continue

        if current_section_index >= 0:
            header, existing_value = sections[current_section_index]
            merged_value = f"{existing_value} | {plain_line}" if existing_value else plain_line
            sections[current_section_index] = (header, merged_value)
            continue

        if not sections:
            intro_lines.append(plain_line)

    section_html = []
    for header, value in sections:
        section_html.append(
            "<div style=\"margin: 0 0 14px 0; padding: 12px 14px; border: 1px solid #e2e8f0; border-radius: 10px;\">"
            f"<div style=\"font-weight: 700; color: #0e7490; margin-bottom: 8px; font-size: 14px; text-transform: uppercase; letter-spacing: 0.02em;\">{html.escape(header)}</div>"
            f"{_format_section_value_html(header, value)}"
            "</div>"
        )

    intro_html = ""
    if intro_lines:
        intro_html = (
            "<div style=\"margin: 0 0 14px 0; color: #334155;\">"
            + "<br>".join(html.escape(line) for line in intro_lines)
            + "</div>"
        )

    fallback_body = _rich_inline_to_html(text or "")
    digest_body = intro_html + "".join(section_html)
    content = digest_body if digest_body else f"<div>{fallback_body}</div>"

    return (
        "<html><body style=\"margin: 0; padding: 20px; background: #f8fafc; font-family: Helvetica, Arial, sans-serif; line-height: 1.5; color: #0f172a;\">"
        "<div style=\"max-width: 720px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 20px;\">"
        f"<h1 style=\"margin: 0 0 16px 0; font-size: 24px; line-height: 1.2;\">{html.escape(title)}</h1>"
        f"{content}"
        "</div>"
        "</body></html>"
    )


def _format_section_value_html(header: str, value: str) -> str:
    """Format section values as paragraph or list for digest email readability."""
    cleaned = (value or "").strip()
    if not cleaned:
        return '<div style="color: #64748b;">(none)</div>'

    normalized_header = (header or "").strip().lower()

    if normalized_header == "date & time":
        parts = [item.strip() for item in re.split(r"\s*\|\s*", cleaned) if item.strip()]
        single_line = ", ".join(parts) if parts else cleaned
        return f'<p style="margin: 0;">{_rich_inline_to_html(_strip_leading_bullet(single_line))}</p>'

    if normalized_header == "news":
        return _format_news_value_html(cleaned)

    if normalized_header == "calendar":
        return _format_calendar_value_html(cleaned)

    if normalized_header == "emails":
        return _format_emails_value_html(cleaned)

    if normalized_header == "key highlights":
        return _format_key_highlights_value_html(cleaned)

    if normalized_header == "tasks":
        parts = [item.strip() for item in re.split(r"\s*\|\s*", cleaned) if item.strip()]
        if not parts:
            return '<div style="color: #64748b;">(none)</div>'
        if len(parts) == 1:
            return f'<p style="margin: 0;">{_render_item_with_url(_strip_leading_bullet(parts[0]))}</p>'
        items = "".join(
            f"<li style=\"margin: 0 0 6px 0;\">{_render_item_with_url(_strip_leading_bullet(p))}</li>"
            for p in parts
        )
        return f'<ul style="margin: 0; padding-left: 18px;">{items}</ul>'

    split_candidates = [item.strip() for item in re.split(r"\s*\|\s*", cleaned) if item.strip()]
    if len(split_candidates) >= 2:
        items = "".join(
            f"<li style=\"margin: 0 0 6px 0;\">{_rich_inline_to_html(_strip_leading_bullet(item))}</li>"
            for item in split_candidates
        )
        return f"<ul style=\"margin: 0; padding-left: 18px;\">{items}</ul>"

    line_items = [item.strip() for item in cleaned.split("; ") if item.strip()]
    if len(line_items) >= 2:
        items = "".join(
            f"<li style=\"margin: 0 0 6px 0;\">{_rich_inline_to_html(_strip_leading_bullet(item))}</li>"
            for item in line_items
        )
        return f"<ul style=\"margin: 0; padding-left: 18px;\">{items}</ul>"

    return f"<p style=\"margin: 0;\">{_rich_inline_to_html(_strip_leading_bullet(cleaned))}</p>"


_EMAIL_PRIORITY_RE = re.compile(r"\s+\((high|medium|low)\):", re.IGNORECASE)


def _extract_link_title(full_text: str, url: str) -> tuple[str, str]:
    """Return (link_title, remainder) — only the short title becomes the link."""
    # Key highlights: "Title (high): reason"
    m = _EMAIL_PRIORITY_RE.search(full_text)
    if m:
        return full_text[:m.start()].strip(), full_text[m.start():]
    if "calendar.google.com" in url or "google.com/calendar" in url:
        # "Event Title @ date ..." → "Event Title"
        parts = full_text.split(" @ ", 1)
        return parts[0].strip(), (" @ " + parts[1]) if len(parts) > 1 else ""
    if "tasks.google.com" in url:
        # "Task title (due ...)" → "Task title"
        for sep in (" (due", " ("):
            if sep in full_text:
                idx = full_text.index(sep)
                return full_text[:idx].strip(), full_text[idx:]
        return full_text, ""
    if "mail.google.com" in url:
        # "Subject - Relation: ..." → "Subject"
        parts = full_text.split(" - ", 1)
        return parts[0].strip(), (" - " + parts[1]) if len(parts) > 1 else ""
    # News: full text is the title
    return full_text, ""


def _render_item_with_url(text: str) -> str:
    """Render text as HTML with only the item title as a clickable link."""
    match = re.match(r"^(.*?)\s*(?:\[\[(https?://[^\]]+)\]\]|- URL:\s*(https?://\S+))\s*$", text)
    if match:
        full_text = match.group(1).strip()
        url = (match.group(2) or match.group(3) or "").strip()
        safe_url = html.escape(url, quote=True)
        link_title, remainder = _extract_link_title(full_text, url)
        safe_title = _rich_inline_to_html(link_title) if link_title else html.escape(url)
        link_html = f'<a href="{safe_url}" style="color: #0e7490; text-decoration: underline;" target="_blank" rel="noopener noreferrer">{safe_title}</a>'
        if remainder:
            return link_html + _rich_inline_to_html(remainder)
        return link_html
    return _rich_inline_to_html(text)


def _format_key_highlights_value_html(value: str) -> str:
    """Render key highlights with news items as clickable links when URLs are present."""
    parts = [item.strip() for item in re.split(r"\s*\|\s*", value) if item.strip()]
    if not parts:
        return '<div style="color: #64748b;">(none)</div>'

    rendered_items = [
        f"<li style=\"margin: 0 0 6px 0;\">{_render_item_with_url(_strip_leading_bullet(part))}</li>"
        for part in parts
    ]
    if len(rendered_items) == 1:
        return f"<p style=\"margin: 0;\">{_render_item_with_url(_strip_leading_bullet(parts[0]))}</p>"
    return f"<ul style=\"margin: 0; padding-left: 18px;\">{''.join(rendered_items)}</ul>"


def _format_calendar_value_html(value: str) -> str:
    """Render calendar section with one bullet per event and inline event details."""
    # Calendar events are joined with " ;; " by calendar_action / synthesize_digest.
    # Split on ";;" first, then fall back to "|" for legacy plain-text paths.
    if ";;" in value:
        parts = [item.strip() for item in value.split(";;") if item.strip()]
    else:
        parts = [item.strip() for item in re.split(r"\s*\|\s*", value) if item.strip()]
    if not parts:
        return '<div style="color: #64748b;">(none)</div>'

    detail_prefixes = (
        "organizer:",
        "attending:",
        "invited:",
        "location:",
        "status:",
        "description:",
    )
    events = []
    for part in parts:
        item = _strip_leading_bullet(part)
        lowered = item.lower()
        is_detail = lowered.startswith(detail_prefixes)
        if is_detail and events:
            events[-1] = f"{events[-1]} | {item}"
            continue
        events.append(item)

    if len(events) == 1:
        return f"<p style=\"margin: 0;\">{_render_item_with_url(events[0])}</p>"

    items = "".join(
        f"<li style=\"margin: 0 0 6px 0;\">{_render_item_with_url(item)}</li>"
        for item in events
    )
    return f"<ul style=\"margin: 0; padding-left: 18px;\">{items}</ul>"


def _format_emails_value_html(value: str) -> str:
    """Render emails section with one bullet per email and inline email details."""
    if ";;" in value:
        parts = [item.strip() for item in value.split(";;") if item.strip()]
    else:
        parts = [item.strip() for item in re.split(r"\s*\|\s*", value) if item.strip()]
    if not parts:
        return '<div style="color: #64748b;">(none)</div>'

    emails = []
    for part in parts:
        item = _strip_leading_bullet(part)
        lowered = item.lower()
        # run_email_action uses this marker in each top-level email item.
        is_email_start = " - relation:" in lowered or lowered.startswith("relation:")
        if is_email_start or not emails:
            emails.append(item)
            continue
        emails[-1] = f"{emails[-1]} | {item}"

    if len(emails) == 1:
        return f"<p style=\"margin: 0;\">{_render_item_with_url(emails[0])}</p>"

    items = "".join(
        f"<li style=\"margin: 0 0 6px 0;\">{_render_item_with_url(item)}</li>"
        for item in emails
    )
    return f"<ul style=\"margin: 0; padding-left: 18px;\">{items}</ul>"


def _format_news_value_html(value: str) -> str:
    """Render news section with clickable article links when URLs are present."""
    items = [item.strip() for item in re.split(r"\s*\|\s*", value) if item.strip()]
    if not items:
        return '<div style="color: #64748b;">(none)</div>'

    fallback_lookup = _build_news_title_url_lookup()

    rendered_items = []
    for item in items:
        item = _strip_leading_bullet(item)
        match = re.match(r"^(.*?)\s*-\s*URL:\s*(https?://\S+)\s*$", item, flags=re.IGNORECASE)
        if match:
            label = match.group(1).strip()
            url = match.group(2).strip()
            safe_url = html.escape(url, quote=True)
            safe_label = _rich_inline_to_html(label) if label else html.escape(url)
            rendered_items.append(
                f"<li style=\"margin: 0 0 6px 0;\"><a href=\"{safe_url}\" style=\"color: #0e7490; text-decoration: underline;\" target=\"_blank\" rel=\"noopener noreferrer\">{safe_label}</a></li>"
            )
            continue

        resolved_url = _resolve_news_url_from_lookup(item, fallback_lookup)
        if resolved_url:
            safe_url = html.escape(resolved_url, quote=True)
            safe_label = _rich_inline_to_html(item)
            rendered_items.append(
                f"<li style=\"margin: 0 0 6px 0;\"><a href=\"{safe_url}\" style=\"color: #0e7490; text-decoration: underline;\" target=\"_blank\" rel=\"noopener noreferrer\">{safe_label}</a></li>"
            )
            continue

        rendered_items.append(
            f"<li style=\"margin: 0 0 6px 0;\">{_rich_inline_to_html(item)}</li>"
        )

    return f"<ul style=\"margin: 0; padding-left: 18px;\">{''.join(rendered_items)}</ul>"


def _rich_inline_to_html(text: str) -> str:
    """Convert a small Rich inline markup subset into HTML."""
    escaped = html.escape(text or "")

    open_tag_map = {
        "bold": "<strong>",
        "italic": "<em>",
        "underline": "<u>",
        "u": "<u>",
        "cyan": '<span style="color: #0e7490;">',
        "bold cyan": '<strong style="color: #0e7490;">',
        "cyan bold": '<strong style="color: #0e7490;">',
    }
    close_tag_map = {
        "bold": "</strong>",
        "italic": "</em>",
        "underline": "</u>",
        "u": "</u>",
        "cyan": "</span>",
        "bold cyan": "</strong>",
        "cyan bold": "</strong>",
    }

    def _replace_open(match: re.Match) -> str:
        token = re.sub(r"\s+", " ", match.group(1).strip().lower())
        return open_tag_map.get(token, "")

    def _replace_close(match: re.Match) -> str:
        token = re.sub(r"\s+", " ", match.group(1).strip().lower())
        return close_tag_map.get(token, "")

    html_text = re.sub(r"\[([^/\]]+?)\]", _replace_open, escaped)
    html_text = re.sub(r"\[/([^\]]+?)\]", _replace_close, html_text)
    html_text = re.sub(r"\[/?[^\]]+\]", "", html_text)
    return html_text.replace("\n", "<br>\n")


def _strip_leading_bullet(text: str) -> str:
    """Remove leading bullet markers so HTML list bullets are not duplicated."""
    return re.sub(r"^\s*[\u2022*\-]+\s*", "", text or "").strip()


def _build_news_title_url_lookup(max_items: int = 15) -> dict:
    """Build a lookup of normalized headline text to URL from cached news action results."""
    records = get_latest_news_records()[:max_items]
    lookup = {}
    for record in records:
        title = (record.get("title") or "").strip()
        url = (record.get("url") or "").strip()
        if not title or not url:
            continue
        lookup[_normalize_news_title(title)] = url
    return lookup


def _resolve_news_url_from_lookup(item_text: str, lookup: dict) -> str:
    """Resolve a URL for a rendered news line by fuzzy title matching."""
    if not lookup:
        return ""
    normalized_item = _normalize_news_title(item_text)
    if normalized_item in lookup:
        return lookup[normalized_item]

    for title_key, url in lookup.items():
        if normalized_item and (normalized_item in title_key or title_key in normalized_item):
            return url
    return ""


def _normalize_news_title(text: str) -> str:
    """Normalize headline text to improve matching between digest lines and feed titles."""
    value = _strip_leading_bullet(text or "")
    value = strip_rich_markup(value)
    value = re.sub(r"\s*\([^)]*\)$", "", value)
    value = re.sub(r"\s*[\-\u2013\u2014]\s*[^\-\u2013\u2014]+$", "", value)
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value
