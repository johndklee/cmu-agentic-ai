"""Prompt redaction helpers for protecting sensitive data sent to the LLM."""

import re


def _mask_email(email: str) -> str:
    """Mask local-part of an email while preserving domain context."""
    local, domain = email.split("@", 1)
    if not local:
        return f"***@{domain}"
    if len(local) == 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + ("*" * (len(local) - 2)) + local[-1]
    return f"{masked_local}@{domain}"


def redact_for_prompt(text: str) -> str:
    """Redact sensitive observation content before sending it to the LLM."""
    redacted = text or ""

    def replace_email(match):
        return _mask_email(match.group(0))

    redacted = re.sub(
        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        replace_email,
        redacted,
        flags=re.IGNORECASE,
    )

    # Remove verbose body preview payloads while preserving that a preview existed.
    # Match until the next top-level email record marker, or end of string.
    redacted = re.sub(
        r"(Body\([^)]*\):)\s*(.*?)(?=\s*\|\s*[^|]+\s+-\s+Relation:|$)",
        r"\1 [REDACTED_PREVIEW]",
        redacted,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return redacted
