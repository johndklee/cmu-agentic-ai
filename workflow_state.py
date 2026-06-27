"""Shared LangGraph workflow state schema."""

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    """Minimal flexible state for multi-agent digest orchestration."""

    raw_fetched_data: dict[str, Any]
    retrieved_corrections: list[dict[str, Any]]
    # ToT level tracking: 1 = generate 5 full rankings, 2 = refine top 2
    tot_level: int
    surviving_candidates: list[dict[str, Any]]    # Top-2 from Level-1 scoring (with scores)
    candidate_rankings: list[dict[str, Any]]      # Level-1 or Level-2 leaf candidates
    scores: list[dict[str, Any]]
    pruning_decisions: list[dict[str, Any]]
    selected_ranking: dict[str, Any] | None
    digest_output: str | dict[str, Any] | None
    user_feedback: dict[str, Any] | None
    node_llm_info: dict[str, str]  # node_name -> human-readable LLM label
