"""Rich display and text formatting helpers."""

import re

from rich import print as rich_print
from rich.panel import Panel


def display_panel(content: str, title: str = "", border_style: str = "") -> None:
    """Render content using Rich panels."""
    rich_print(Panel(content, title=title, border_style=border_style or "white"))


def summarize_for_display(text: str, max_chars: int = 900) -> str:
    """Trim long strings for terminal display while keeping full internal values elsewhere."""
    content = str(text or "")
    if len(content) <= max_chars:
        return content
    hidden = len(content) - max_chars
    return f"{content[:max_chars]}\n... [truncated {hidden} chars for display]"


def to_single_line(text: str) -> str:
    """Collapse all whitespace in a string into a single spaced line."""
    return re.sub(r"\s+", " ", text).strip()


def strip_rich_markup(text: str) -> str:
    """Remove Rich-style markup tags from text."""
    return re.sub(r"\[/?[^\]]+\]", "", text)


def enforce_single_line_digest_fields(text: str) -> str:
    """Force Location/Date/Time/Weather digest fields to remain one line each."""
    lines = text.splitlines()
    if not lines:
        return text

    field_names = {"location", "date", "time", "weather"}

    def is_field_line(line: str) -> bool:
        plain = strip_rich_markup(line).strip().lower()
        return any(plain.startswith(f"{name}:") for name in field_names)

    def starts_new_section(line: str) -> bool:
        plain = strip_rich_markup(line).strip()
        return bool(re.match(r"^[A-Za-z][A-Za-z ]*:\s*", plain))

    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not is_field_line(line):
            out.append(line)
            i += 1
            continue

        merged = to_single_line(line)
        j = i + 1
        while j < len(lines):
            candidate = lines[j]
            candidate_plain = strip_rich_markup(candidate).strip()
            if not candidate_plain:
                break
            if is_field_line(candidate) or starts_new_section(candidate):
                break
            merged = to_single_line(f"{merged} {candidate_plain}")
            j += 1

        out.append(merged)
        i = j

    return "\n".join(out)
