"""Shadow-mode Agent B wrapper for key highlights contract validation."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

SHADOW_LOG_PATH = Path(__file__).with_name(".memory") / "key_highlights_shadow.jsonl"

ALLOWED_CATEGORIES = {"calendar", "emails", "tasks", "weather", "news", "mixed"}


def _split_items(value: str, max_items: int = 5) -> List[str]:
    """Split pipe-delimited text into compact list items."""
    items = [part.strip() for part in (value or "").split("|") if part.strip()]
    return items[:max_items]


def _extract_current_highlights(payload: dict, max_items: int = 5) -> List[str]:
    """Extract currently-rendered key highlights from payload for shadow comparison."""
    sections = (payload or {}).get("sections", {}) or {}
    return _split_items(sections.get("key_highlights", ""), max_items=max_items)


def _overlap_ratio(current_items: List[str], shadow_items: List[str]) -> float:
    """Compute overlap ratio between current and shadow highlight texts."""
    current_set = {item.strip().lower() for item in current_items if item.strip()}
    shadow_set = {item.strip().lower() for item in shadow_items if item.strip()}
    if not current_set:
        return 1.0 if not shadow_set else 0.0
    return len(current_set & shadow_set) / len(current_set)


def _ordering_changes(current_items: List[str], shadow_items: List[str]) -> int:
    """Count shared highlights that moved index between current and shadow outputs."""
    current_index = {item.strip().lower(): idx for idx, item in enumerate(current_items) if item.strip()}
    shadow_index = {item.strip().lower(): idx for idx, item in enumerate(shadow_items) if item.strip()}
    shared = set(current_index) & set(shadow_index)
    return sum(1 for item in shared if current_index[item] != shadow_index[item])


def build_agent_b_input(payload: dict) -> dict:
    """Build minimal Agent B input from canonical digest payload."""
    sections = (payload or {}).get("sections", {}) or {}
    constraints = {"max_highlights": 5, "max_chars_each": 180}
    return {
        "digest_title": (payload or {}).get("title", "Daily Digest"),
        "date_time": f"{(payload or {}).get('date', 'Unknown')} | {(payload or {}).get('time', 'Unknown')}",
        "location": (payload or {}).get("location", "Unknown"),
        "weather": sections.get("weather", "Unknown"),
        "news_items": [{"title": item, "source": "", "url": ""} for item in _split_items(sections.get("news", ""), 8)],
        "calendar_items": [{"summary": item, "start": "", "end": "", "attendees": []} for item in _split_items(sections.get("calendar", ""), 8)],
        "task_items": [{"title": item, "status": "", "due": ""} for item in _split_items(sections.get("tasks", ""), 8)],
        "email_items": [
            {"subject": item, "from": "", "relation": "", "vip": "", "preview": ""}
            for item in _split_items(sections.get("emails", ""), 8)
        ],
        "preferences": {"temperature_unit": "C", "digest_preferences_summary": ""},
        "constraints": constraints,
        "seed_key_highlights": _split_items(sections.get("key_highlights", ""), constraints["max_highlights"]),
    }


def _build_candidate_output(agent_input: dict) -> dict:
    """Build a deterministic candidate output for schema validation in shadow mode."""
    constraints = agent_input.get("constraints", {}) or {}
    max_highlights = int(constraints.get("max_highlights", 5) or 5)
    max_chars_each = int(constraints.get("max_chars_each", 180) or 180)

    seed = agent_input.get("seed_key_highlights") or []
    highlights = []
    for index, item in enumerate(seed[:max_highlights], start=1):
        text = item.strip()
        if len(text) > max_chars_each:
            text = text[: max(0, max_chars_each - 3)].rstrip() + "..."
        highlights.append(
            {
                "rank": index,
                "text": text,
                "category": "mixed",
                "evidence": ["sections.key_highlights"],
            }
        )

    if not highlights:
        highlights = [
            {
                "rank": 1,
                "text": "No key highlights available from current observations.",
                "category": "mixed",
                "evidence": ["sections.key_highlights"],
            }
        ]

    return {"highlights": highlights, "confidence": "medium"}


def validate_agent_b_output(output: dict, constraints: dict) -> Tuple[bool, List[str]]:
    """Validate Agent B output against minimal contract rules."""
    errors = []

    if not isinstance(output, dict):
        return False, ["output must be an object"]

    highlights = output.get("highlights")
    if not isinstance(highlights, list):
        return False, ["highlights must be a list"]

    max_highlights = int((constraints or {}).get("max_highlights", 5) or 5)
    max_chars_each = int((constraints or {}).get("max_chars_each", 180) or 180)

    if not (1 <= len(highlights) <= max_highlights):
        errors.append("highlights length out of bounds")

    expected_rank = 1
    for entry in highlights:
        if not isinstance(entry, dict):
            errors.append("highlight entry must be an object")
            continue

        rank = entry.get("rank")
        if rank != expected_rank:
            errors.append("rank sequence must start at 1 and be contiguous")
        expected_rank += 1

        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append("highlight text must be a non-empty string")
        elif len(text) > max_chars_each:
            errors.append("highlight text exceeds max_chars_each")

        category = entry.get("category")
        if category not in ALLOWED_CATEGORIES:
            errors.append("highlight category is invalid")

        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
            errors.append("evidence must be a list of strings")

    confidence = output.get("confidence")
    if confidence not in {"low", "medium", "high"}:
        errors.append("confidence must be low, medium, or high")

    return len(errors) == 0, errors


def run_key_highlights_shadow(payload: dict) -> Dict[str, object]:
    """Run Agent B wrapper in shadow mode and return validation diagnostics."""
    agent_input = build_agent_b_input(payload)
    candidate = _build_candidate_output(agent_input)
    is_valid, errors = validate_agent_b_output(candidate, agent_input.get("constraints", {}))
    current_items = _extract_current_highlights(payload, max_items=5)
    shadow_highlights = [entry.get("text", "") for entry in candidate.get("highlights", []) if isinstance(entry, dict)]
    overlap_ratio = round(_overlap_ratio(current_items, shadow_highlights), 4)
    ordering_changes = int(_ordering_changes(current_items, shadow_highlights))
    return {
        "invoked": True,
        "schema_valid": is_valid,
        "errors": errors,
        "highlights_count": len(candidate.get("highlights", [])),
        "confidence": candidate.get("confidence", "low"),
        "shadow_highlights": shadow_highlights,
        "overlap_ratio": overlap_ratio,
        "ordering_changes": ordering_changes,
        "empty_result": len(candidate.get("highlights", [])) == 0,
        "timed_out": False,
        "error": "",
    }


def should_promote_shadow_result(
    result: dict,
    min_overlap_ratio: float = 0.6,
    max_ordering_changes: int = 2,
) -> Tuple[bool, List[str]]:
    """Evaluate whether a shadow result is safe to promote into production output."""
    failures = []
    result = result or {}

    if not bool(result.get("schema_valid", False)):
        failures.append("schema_invalid")

    if str(result.get("confidence", "low")) not in {"medium", "high"}:
        failures.append("confidence_too_low")

    if bool(result.get("timed_out", False)):
        failures.append("timed_out")

    overlap_ratio = float(result.get("overlap_ratio", 0.0) or 0.0)
    if overlap_ratio < float(min_overlap_ratio):
        failures.append("overlap_below_threshold")

    ordering_changes = int(result.get("ordering_changes", 0) or 0)
    if ordering_changes > int(max_ordering_changes):
        failures.append("ordering_changes_above_threshold")

    if bool(result.get("empty_result", False)) or int(result.get("highlights_count", 0) or 0) <= 0:
        failures.append("empty_result")

    return len(failures) == 0, failures


def log_shadow_comparison(payload: dict, result: dict, run_id: str) -> str:
    """Append shadow comparison metrics to JSONL log and return path."""
    current_items = _extract_current_highlights(payload, max_items=5)
    shadow_items = [item for item in (result or {}).get("shadow_highlights", []) if isinstance(item, str)]

    record = {
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "schema_valid": bool((result or {}).get("schema_valid", False)),
        "confidence": str((result or {}).get("confidence", "low")),
        "highlights_count": int((result or {}).get("highlights_count", 0) or 0),
        "overlap_ratio": float((result or {}).get("overlap_ratio", round(_overlap_ratio(current_items, shadow_items), 4))),
        "ordering_changes": int((result or {}).get("ordering_changes", _ordering_changes(current_items, shadow_items))),
        "empty_result": bool((result or {}).get("empty_result", int((result or {}).get("highlights_count", 0) or 0) == 0)),
        "timed_out": bool((result or {}).get("timed_out", False)),
        "error": str((result or {}).get("error", "") or ""),
        "agent_a_highlights": current_items,
        "agent_b_highlights": shadow_items,
    }

    SHADOW_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SHADOW_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    return str(SHADOW_LOG_PATH)
