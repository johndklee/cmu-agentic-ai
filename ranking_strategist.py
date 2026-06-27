"""Ranking strategist agent for ToT candidate generation."""

import json
import os
import re
from typing import Any

from llm_client import OLLAMA_DEFAULT_MODEL, _generate_with_ollama
from crewai_agents import run_crewai_ranking_strategist
from preferences import load_preferences
from workflow_state import WorkflowState

MAX_CANDIDATES = 5
ALLOWED_PRIORITIES = {"high", "medium", "low"}


def _resolve_ollama_model() -> str:
    """Resolve Ollama model for strategist generation."""
    return (
        os.getenv("OLLAMA_MODEL", "").strip()
        or OLLAMA_DEFAULT_MODEL
    )


def _build_rankable_items(raw_fetched_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert raw fetched payload into rankable digest items."""
    items: list[dict[str, Any]] = []

    for index, event in enumerate(raw_fetched_data.get("calendar_events", []) or [], start=1):
        attendees = event.get("attendees") or []
        attendee_is_vip = any(bool(a.get("is_vip")) for a in attendees if isinstance(a, dict))
        items.append(
            {
                "item_id": f"calendar:{event.get('id') or index}",
                "source": "calendar_events",
                "summary": event.get("summary") or "(no title)",
                "signals": {
                    "organizer_is_vip": bool(event.get("organizer_is_vip", False)),
                    "attendee_is_vip": attendee_is_vip,
                    "attendee_count": len(attendees),
                },
            }
        )

    for index, email in enumerate(raw_fetched_data.get("emails", []) or [], start=1):
        items.append(
            {
                "item_id": f"emails:{email.get('id') or index}",
                "source": "emails",
                "summary": email.get("subject") or "(no subject)",
                "signals": {
                    "is_unread": bool(email.get("is_unread", False)),
                    "vip_matches": len(email.get("vip_matches", []) or []),
                },
            }
        )

    for index, task in enumerate(raw_fetched_data.get("tasks", []) or [], start=1):
        items.append(
            {
                "item_id": f"tasks:{task.get('id') or index}",
                "source": "tasks",
                "summary": task.get("title") or "(untitled task)",
                "signals": {
                    "has_due": bool(task.get("due")),
                },
            }
        )

    for index, headline in enumerate(raw_fetched_data.get("news", []) or [], start=1):
        items.append(
            {
                "item_id": f"news:{index}",
                "source": "news",
                "summary": headline.get("title") or "(untitled headline)",
                "signals": {},
            }
        )

    weather = raw_fetched_data.get("weather") or {}
    if isinstance(weather, dict) and weather:
        items.append(
            {
                "item_id": "weather:current",
                "source": "weather",
                "summary": weather.get("description") or "Current weather",
                "signals": {
                    "temperature_c": weather.get("temperature_c"),
                },
            }
        )

    return items


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """Extract JSON array payload from plain or fenced model output."""
    cleaned = (text or "").strip()
    fenced_match = re.search(r"```(?:json)?\s*(\[.*\])\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        cleaned = fenced_match.group(1).strip()

    parsed = json.loads(cleaned)
    if isinstance(parsed, list):
        return parsed

    array_match = re.search(r"(\[\s*\{.*\}\s*\])", cleaned, flags=re.DOTALL)
    if array_match:
        parsed = json.loads(array_match.group(1))
        if isinstance(parsed, list):
            return parsed

    raise ValueError("Model output did not contain a JSON array.")


def _candidate_score(item: dict[str, Any]) -> int:
    """Compute a lightweight score for deterministic fallback rankings."""
    source = item.get("source", "")
    signals = item.get("signals") or {}
    score = 0
    if source == "tasks":
        score += 5
        if signals.get("has_due"):
            score += 2
    elif source == "calendar_events":
        score += 4
        if signals.get("organizer_is_vip"):
            score += 2
        if signals.get("attendee_is_vip"):
            score += 2
    elif source == "emails":
        score += 3
        if signals.get("is_unread"):
            score += 2
        score += int(signals.get("vip_matches") or 0)
    elif source == "weather":
        score += 2
    elif source == "news":
        score += 1
    return score


def _human_reason(item: dict[str, Any], priority: str) -> str:
    """Return a human-readable reason for why an item was ranked at a given priority."""
    source = item.get("source", "")
    signals = item.get("signals") or {}
    summary = item.get("summary", "")
    if source == "tasks":
        if signals.get("has_due"):
            return f"Task due soon — needs attention."
        return "Open task requiring follow-up."
    if source == "calendar_events":
        if signals.get("organizer_is_vip"):
            return "Upcoming meeting with a VIP contact."
        if signals.get("attendee_count", 0) > 2:
            return f"Upcoming meeting with {signals['attendee_count']} attendees."
        return "Upcoming calendar event."
    if source == "emails":
        parts = []
        if signals.get("is_unread"):
            parts.append("unread")
        if signals.get("vip_matches", 0) > 0:
            parts.append("from a VIP contact")
        return ("Email " + " and ".join(parts) + ".").strip() if parts else "Email requiring review."
    if source == "news":
        return "Relevant news item for today."
    if source == "weather":
        return "Current weather conditions."
    return f"{summary or 'Item'} ranked {priority} priority."


def _fallback_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build deterministic fallback rankings when model output is invalid."""
    ordered = sorted(items, key=_candidate_score, reverse=True)
    if not ordered:
        return [
            {
                "candidate_id": f"candidate_{idx}",
                "strategy": "fallback_empty",
                "ranking": [],
            }
            for idx in range(1, MAX_CANDIDATES + 1)
        ]

    candidates: list[dict[str, Any]] = []
    for idx in range(MAX_CANDIDATES):
        rotated = ordered[idx:] + ordered[:idx]
        ranking = []
        for rank_index, item in enumerate(rotated, start=1):
            if rank_index <= 3:
                priority = "high"
            elif rank_index <= 6:
                priority = "medium"
            else:
                priority = "low"
            ranking.append(
                {
                    "item_id": item["item_id"],
                    "source": item["source"],
                    "priority": priority,
                    "reason": _human_reason(item, priority),
                }
            )
        candidates.append(
            {
                "candidate_id": f"candidate_{idx + 1}",
                "strategy": "fallback_rotation",
                "ranking": ranking,
            }
        )
    return candidates


def _validate_candidates(candidates: list[dict[str, Any]], valid_item_ids: set[str]) -> list[dict[str, Any]]:
    """Filter and normalize model candidates to expected schema."""
    normalized: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            continue
        ranking_entries = candidate.get("ranking")
        if not isinstance(ranking_entries, list):
            continue

        normalized_ranking = []
        for entry in ranking_entries:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("item_id") or "").strip()
            source = str(entry.get("source") or "").strip()
            priority = str(entry.get("priority") or "").strip().lower()
            reason = str(entry.get("reason") or "").strip()
            if not item_id or item_id not in valid_item_ids:
                continue
            if priority not in ALLOWED_PRIORITIES:
                continue
            normalized_ranking.append(
                {
                    "item_id": item_id,
                    "source": source,
                    "priority": priority,
                    "reason": reason or "No reason provided.",
                }
            )

        normalized.append(
            {
                "candidate_id": str(candidate.get("candidate_id") or f"candidate_{index}"),
                "strategy": str(candidate.get("strategy") or "llm_generated"),
                "ranking": normalized_ranking,
            }
        )

    return normalized


SURVIVORS = 2  # top candidates carried from Level 1 to Level 2


def _build_prompt(items: list[dict[str, Any]], corrections: list[dict[str, Any]], min_highlights: int = 5) -> str:
    """Level-1 prompt: generate 5 full candidate rankings."""
    return (
        "You are a ranking strategist for a daily digest.\n"
        "Generate exactly 5 Tree-of-Thought candidate rankings.\n"
        "Use only the provided item_id values.\n"
        "Output JSON only: an array with exactly 5 objects.\n"
        "Each candidate object must have keys: candidate_id, strategy, ranking.\n"
        "Each ranking entry must have keys: item_id, source, priority (high|medium|low), reason.\n"
        f"CRITICAL: Each ranking array MUST contain EXACTLY {min_highlights} or more entries. "
        f"You MUST include at least {min_highlights} items in every ranking array. "
        f"A ranking with fewer than {min_highlights} entries is INVALID and will be rejected. "
        "Rank ALL available items if there are fewer than the minimum.\n"
        "Do not include markdown fences.\n\n"
        f"Rankable items ({len(items)} total):\n{json.dumps(items, ensure_ascii=True)}\n\n"
        f"Retrieved corrections:\n{json.dumps(corrections[:20], ensure_ascii=True)}\n"
    )


def _build_refinement_prompt(
    candidate: dict[str, Any],
    scores: dict[str, float],
    items: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    variant: int,
    min_highlights: int = 5,
) -> str:
    """Level-2 prompt: refine one surviving candidate into an improved ranking."""
    weaknesses = []
    if scores.get("meeting_proximity", 1.0) < 0.5:
        weaknesses.append("move calendar events with imminent start times higher")
    if scores.get("vip_alignment", 1.0) < 0.5:
        weaknesses.append("elevate items involving VIP contacts")
    if scores.get("episodic_consistency", 1.0) < 0.5:
        weaknesses.append("better reflect past user priority corrections")
    if scores.get("coherence", 1.0) < 0.5:
        weaknesses.append("improve overall priority coherence and reasoning clarity")
    weakness_text = "; ".join(weaknesses) if weaknesses else "maintain strengths and refine reasoning"

    return (
        f"You are a digest ranking strategist. Level 2 refinement — variant {variant}.\n"
        f"The candidate below scored: meeting_proximity={scores.get('meeting_proximity', 0):.2f}, "
        f"vip_alignment={scores.get('vip_alignment', 0):.2f}, "
        f"episodic_consistency={scores.get('episodic_consistency', 0):.2f}, "
        f"coherence={scores.get('coherence', 0):.2f}.\n"
        f"Improvement focus: {weakness_text}.\n"
        "Output JSON only: a single object (not an array).\n"
        "Keys: candidate_id (string), strategy (string), ranking (array).\n"
        "Each ranking entry: item_id, source, priority (high|medium|low), reason.\n"
        f"CRITICAL: The ranking array MUST contain EXACTLY {min_highlights} or more entries. "
        f"A ranking with fewer than {min_highlights} entries is INVALID and will be rejected. "
        "Rank ALL available items if there are fewer than the minimum.\n"
        "Use only the provided item_id values. Do not include markdown fences.\n\n"
        f"Original ranking to improve:\n{json.dumps(candidate.get('ranking', []), ensure_ascii=True)}\n\n"
        f"Available items:\n{json.dumps(items, ensure_ascii=True)}\n\n"
        f"Past corrections:\n{json.dumps(corrections[:10], ensure_ascii=True)}\n"
    )


def _refine_candidate(
    candidate: dict[str, Any],
    scores: dict[str, float],
    items: list[dict[str, Any]],
    valid_item_ids: set[str],
    corrections: list[dict[str, Any]],
    variant: int,
    min_highlights: int = 5,
) -> dict[str, Any] | None:
    """Generate one refined version of a surviving Level-1 candidate."""
    prompt = _build_refinement_prompt(candidate, scores, items, corrections, variant, min_highlights=min_highlights)
    try:
        from llm_client import _generate_with_ollama, OLLAMA_DEFAULT_MODEL
        model = os.getenv("OLLAMA_MODEL", "").strip() or OLLAMA_DEFAULT_MODEL
        text = _generate_with_ollama(prompt=prompt, model=model)
        cleaned = (text or "").strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1).strip()
        parsed = json.loads(cleaned)
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if not isinstance(parsed, dict):
            return None
        normalized = _validate_candidates([parsed], valid_item_ids)
        if normalized:
            refined = normalized[0]
            refined["candidate_id"] = f"{candidate.get('candidate_id', 'c')}_r{variant}"
            refined["strategy"] = f"refined:{candidate.get('strategy', 'llm_generated')}"
            return refined
    except Exception:
        pass
    return None


def ranking_strategist(state: WorkflowState) -> WorkflowState:
    """2-level BFS Tree-of-Thought strategist.

    Level 1: generate 5 full candidate rankings via CrewAI (Ollama).
    Level 2: refine the top 2 survivors — 2 variants each → 4 leaf candidates.
    """
    next_state: WorkflowState = dict(state)
    raw_fetched_data = state.get("raw_fetched_data") or {}
    corrections = state.get("retrieved_corrections") or []
    tot_level = state.get("tot_level") or 1

    prefs = load_preferences()
    min_highlights = int(prefs.get("preferred_highlight_count") or 5)

    items = _build_rankable_items(raw_fetched_data if isinstance(raw_fetched_data, dict) else {})
    valid_item_ids = {item["item_id"] for item in items}

    strategist_llm = f"Ollama ({_resolve_ollama_model()})"
    llm_info = dict(state.get("node_llm_info") or {})
    llm_info["strategist"] = strategist_llm
    next_state["node_llm_info"] = llm_info

    if tot_level == 1:
        # ── Level 1: generate 5 full candidate rankings ────────────────────
        try:
            candidates = run_crewai_ranking_strategist(state, min_highlights=min_highlights)
        except Exception:
            candidates = []
        if len(candidates) != MAX_CANDIDATES:
            candidates = _fallback_candidates(items)
        next_state["candidate_rankings"] = candidates
        next_state["tot_level"] = 1

    else:
        # ── Level 2: refine the top-2 survivors ───────────────────────────
        surviving = state.get("surviving_candidates") or []
        if not surviving:
            surviving = (state.get("candidate_rankings") or [])[:SURVIVORS]

        leaf_candidates: list[dict[str, Any]] = []
        for entry in surviving[:SURVIVORS]:
            candidate = entry.get("candidate") or {}
            scores = entry.get("scores") or {}
            for variant in range(1, 3):  # 2 refined variants per survivor
                refined = _refine_candidate(candidate, scores, items, valid_item_ids, corrections, variant, min_highlights=min_highlights)
                if refined:
                    leaf_candidates.append(refined)

        # Fallback: if refinement failed, carry survivors forward as-is
        if not leaf_candidates:
            leaf_candidates = [e.get("candidate") for e in surviving if e.get("candidate")]

        next_state["candidate_rankings"] = leaf_candidates
        next_state["tot_level"] = 2

    return next_state
