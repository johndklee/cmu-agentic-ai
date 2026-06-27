"""Ranking critic agent for scoring and pruning candidate rankings."""

import json
from typing import Any

from crewai_agents import run_crewai_ranking_critic
from critic_tools import episodic_consistency_tool, meeting_proximity_tool, vip_alignment_tool
from workflow_state import WorkflowState


def _map_items_by_id(raw_fetched_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build lookup map from item_id to raw source item for deterministic checks."""
    mapped: dict[str, dict[str, Any]] = {}

    for index, event in enumerate(raw_fetched_data.get("calendar_events", []) or [], start=1):
        mapped[f"calendar:{event.get('id') or index}"] = event

    for index, email in enumerate(raw_fetched_data.get("emails", []) or [], start=1):
        mapped[f"emails:{email.get('id') or index}"] = email

    for index, task in enumerate(raw_fetched_data.get("tasks", []) or [], start=1):
        mapped[f"tasks:{task.get('id') or index}"] = task

    for index, headline in enumerate(raw_fetched_data.get("news", []) or [], start=1):
        mapped[f"news:{index}"] = headline

    weather = raw_fetched_data.get("weather") or {}
    if isinstance(weather, dict) and weather:
        mapped["weather:current"] = weather

    return mapped



def _coherence_score_with_claude(candidate: dict[str, Any]) -> tuple[float, str]:
    """Evaluate candidate coherence via CrewAI critic. Returns (score, llm_label)."""
    try:
        return run_crewai_ranking_critic(candidate)
    except Exception:
        return 0.5, "none (error fallback)"


def _total_score(meeting_proximity: float, vip_alignment: float, episodic_consistency: float, coherence: float) -> float:
    """Weighted aggregate score for one candidate."""
    score = (
        0.35 * meeting_proximity
        + 0.35 * vip_alignment
        + 0.15 * episodic_consistency
        + 0.15 * coherence
    )
    return round(score, 4)


def _extract_refinement_round(pruning_decisions: list[dict[str, Any]]) -> int:
    """Extract latest refinement round count from previous pruning metadata."""
    round_value = 0
    for decision in pruning_decisions or []:
        if not isinstance(decision, dict):
            continue
        if str(decision.get("candidate_id") or "") != "__controller__":
            continue
        try:
            round_value = max(round_value, int(decision.get("refinement_round", 0) or 0))
        except (TypeError, ValueError):
            continue
    return round_value


def _should_refine(scores: list[dict[str, Any]], current_round: int, max_rounds: int = 2) -> bool:
    """Return whether another strategist refinement round is warranted."""
    if current_round >= max_rounds:
        return False
    if len(scores) < 2:
        return False
    ordered = sorted(scores, key=lambda row: float(row.get("total", 0.0)), reverse=True)
    top_score = float(ordered[0].get("total", 0.0))
    second_score = float(ordered[1].get("total", 0.0))
    return (top_score - second_score) < 0.08


def _build_pruning_decisions(scores: list[dict[str, Any]], keep_top_n: int = 2) -> list[dict[str, Any]]:
    """Create prune/keep decisions based on aggregate score ordering."""
    ordered = sorted(scores, key=lambda row: float(row.get("total", 0.0)), reverse=True)
    keep_ids = {row.get("candidate_id") for row in ordered[:keep_top_n]}

    decisions = []
    for row in ordered:
        candidate_id = row.get("candidate_id")
        keep = candidate_id in keep_ids
        decisions.append(
            {
                "candidate_id": candidate_id,
                "decision": "keep" if keep else "prune",
                "rationale": (
                    "Top aggregate score across deterministic checks, episodic consistency, and coherence."
                    if keep
                    else "Lower aggregate score than retained candidates."
                ),
            }
        )
    return decisions


def _score_candidates(
    candidates: list[dict[str, Any]],
    raw_fetched_data: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """Run all 4 scoring criteria against every candidate.

    Returns (score_rows, critic_llm_label).
    """
    item_map = _map_items_by_id(raw_fetched_data)
    item_map_json = json.dumps(item_map)
    scores = []
    critic_llm_label = "none"
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        candidate_json = json.dumps(candidate)

        meeting_proximity = float(meeting_proximity_tool.invoke(
            {"candidate_json": candidate_json, "item_map_json": item_map_json}
        ))
        vip_alignment = float(vip_alignment_tool.invoke(
            {"candidate_json": candidate_json, "item_map_json": item_map_json}
        ))
        episodic_result = json.loads(episodic_consistency_tool.invoke(
            {"candidate_json": candidate_json, "item_map_json": item_map_json}
        ))
        episodic_consistency = float(episodic_result.get("score", 0.0))
        retrieved_count = int(episodic_result.get("retrieved_count", 0))
        coherence, critic_llm_label = _coherence_score_with_claude(candidate)
        total = _total_score(meeting_proximity, vip_alignment, episodic_consistency, coherence)

        scores.append({
            "candidate_id": candidate_id,
            "meeting_proximity": meeting_proximity,
            "vip_alignment": vip_alignment,
            "episodic_consistency": episodic_consistency,
            "coherence": coherence,
            "episodic_matches": retrieved_count,
            "total": total,
        })
    return scores, critic_llm_label


def ranking_critic(state: WorkflowState) -> WorkflowState:
    """2-level BFS critic matching the spec.

    Level 1: score all 5 full candidates with 4-criterion rubric, prune to top 2,
             signal strategist to refine those survivors.
    Level 2: score all refined leaf candidates (up to 4), select best, proceed to synthesis.
    """
    next_state: WorkflowState = dict(state)
    raw_fetched_data = state.get("raw_fetched_data") if isinstance(state.get("raw_fetched_data"), dict) else {}
    candidates = state.get("candidate_rankings") if isinstance(state.get("candidate_rankings"), list) else []
    tot_level = state.get("tot_level") or 1

    scores, critic_llm_label = _score_candidates(candidates, raw_fetched_data)
    llm_info = dict(state.get("node_llm_info") or {})
    llm_info["critic"] = critic_llm_label
    next_state["node_llm_info"] = llm_info

    if tot_level == 1:
        # ── Level-1 critic: score 5 candidates, keep top 2 for refinement ──
        pruning = _build_pruning_decisions(scores, keep_top_n=2)

        ordered = sorted(scores, key=lambda r: float(r.get("total", 0.0)), reverse=True)
        by_id = {c.get("candidate_id"): c for c in candidates if isinstance(c, dict)}
        surviving_candidates = [
            {"candidate": by_id[row["candidate_id"]], "scores": row}
            for row in ordered[:2]
            if row.get("candidate_id") in by_id
        ]

        pruning.append({
            "candidate_id": "__controller__",
            "decision": "expand",
            "tot_level": 1,
            "rationale": f"Top 2 candidates selected for Level-2 refinement.",
        })
        next_state["scores"] = scores
        next_state["pruning_decisions"] = pruning
        next_state["surviving_candidates"] = surviving_candidates
        next_state["tot_level"] = 1

    else:
        # ── Level-2 critic: score refined leaves, select best, proceed ──────
        pruning = _build_pruning_decisions(scores, keep_top_n=1)
        pruning.append({
            "candidate_id": "__controller__",
            "decision": "proceed",
            "tot_level": 2,
            "rationale": "Level-2 refinement scoring complete; best candidate selected.",
        })
        next_state["scores"] = scores
        next_state["pruning_decisions"] = pruning

    return next_state
