"""LangChain tool wrappers for deterministic critic scoring functions."""

import json
from typing import Any

from langchain_core.tools import tool

from memory_store import EpisodicMemoryStore


@tool
def meeting_proximity_tool(candidate_json: str, item_map_json: str) -> float:
    """Score a candidate ranking by how close calendar events are to the top.

    Args:
        candidate_json: JSON-serialized candidate ranking dict.
        item_map_json: JSON-serialized item_id -> source item map.

    Returns:
        Float score between 0.0 and 1.0.
    """
    candidate: dict[str, Any] = json.loads(candidate_json)
    item_map: dict[str, Any] = json.loads(item_map_json)

    ranking = candidate.get("ranking") or []
    if not ranking:
        return 0.0

    score = 0.0
    cal_count = 0
    for idx, entry in enumerate(ranking[:5], start=1):
        item_id = str(entry.get("item_id") or "")
        if not item_id.startswith("calendar:"):
            continue
        cal_count += 1
        score += max(0.0, (6 - idx) / 5.0)

    if cal_count == 0:
        return 0.0
    return min(1.0, score / float(cal_count))


@tool
def vip_alignment_tool(candidate_json: str, item_map_json: str) -> float:
    """Score a candidate ranking by how well VIP-involved items are prioritized.

    Args:
        candidate_json: JSON-serialized candidate ranking dict.
        item_map_json: JSON-serialized item_id -> source item map.

    Returns:
        Float score between 0.0 and 1.0.
    """
    candidate: dict[str, Any] = json.loads(candidate_json)
    item_map: dict[str, Any] = json.loads(item_map_json)

    ranking = candidate.get("ranking") or []
    if not ranking:
        return 0.0

    weighted_hits = 0.0
    possible = 0.0
    for idx, entry in enumerate(ranking[:8], start=1):
        item_id = str(entry.get("item_id") or "")
        item = item_map.get(item_id, {})
        weight = max(0.2, (9 - idx) / 8.0)

        has_vip = False
        if item_id.startswith("emails:"):
            has_vip = bool(item.get("vip_matches"))
        elif item_id.startswith("calendar:"):
            has_vip = bool(item.get("organizer_is_vip")) or any(
                bool(att.get("is_vip")) for att in (item.get("attendees") or []) if isinstance(att, dict)
            )

        if has_vip:
            weighted_hits += weight
        possible += weight

    if possible <= 0:
        return 0.0
    return min(1.0, weighted_hits / possible)


@tool
def episodic_consistency_tool(candidate_json: str, item_map_json: str) -> str:
    """Score a candidate ranking against past episodic corrections from ChromaDB.

    Args:
        candidate_json: JSON-serialized candidate ranking dict.
        item_map_json: JSON-serialized item_id -> source item map.

    Returns:
        JSON string with keys 'score' (float) and 'retrieved_count' (int).
    """
    candidate: dict[str, Any] = json.loads(candidate_json)
    item_map: dict[str, Any] = json.loads(item_map_json)

    ranking = candidate.get("ranking") or []
    if not ranking:
        return json.dumps({"score": 0.0, "retrieved_count": 0})

    query_parts = []
    for entry in ranking[:5]:
        item_id = str(entry.get("item_id") or "")
        priority = str(entry.get("priority") or "")
        reason = str(entry.get("reason") or "")
        source_item = item_map.get(item_id, {})
        summary = (
            source_item.get("summary")
            or source_item.get("subject")
            or source_item.get("title")
            or item_id
        )
        query_parts.append(f"{summary} priority={priority} reason={reason}")

    query = " | ".join(query_parts)
    store = EpisodicMemoryStore()
    matches = store.retrieve_similar(query, correction_type="priority_override", top_k=5)

    if not matches:
        return json.dumps({"score": 0.0, "retrieved_count": 0})

    quality_hits = sum(
        1
        for match in matches
        if str(match.get("correction_type") or "") == "priority_override"
        or any(
            token in str(match.get("correction_text") or "").lower()
            for token in ("priority", "rank", "vip", "urgent", "top")
        )
    )

    score = min(1.0, quality_hits / float(len(matches)))
    return json.dumps({"score": score, "retrieved_count": len(matches)})
