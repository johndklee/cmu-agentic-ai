"""LangGraph controller scaffolding for multi-agent workflow execution."""

import importlib
import json
from datetime import datetime, timezone
from typing import Any

from fetcher_agent import fetcher_agent
from feedback_agent import user_feedback_agent
from mcp_branch_state import reset_branch_state, mcp_call
from memory_store import EpisodicMemoryStore, format_retrieved_corrections
from ranking_critic import ranking_critic
from ranking_strategist import ranking_strategist
from synthesize_digest import synthesize_digest
from workflow_state import WorkflowState

CompiledStateGraph = Any

_FETCH_SOURCES = {"calendar_events", "emails", "tasks", "news", "weather"}


def _require(condition: bool, node: str, message: str) -> None:
    """Raise RuntimeError with a consistent inter-node guard message."""
    if not condition:
        raise RuntimeError(f"[{node}] precondition failed: {message}")


def fetcher_node(state: WorkflowState) -> WorkflowState:
    """Fetch initial raw data from external sources into workflow state."""
    reset_branch_state()
    next_state = fetcher_agent(state)
    raw = next_state.get("raw_fetched_data")
    _require(isinstance(raw, dict) and bool(raw), "fetcher", "raw_fetched_data is empty or missing")
    populated = [k for k in _FETCH_SOURCES if raw.get(k)]
    _require(len(populated) >= 1, "fetcher", f"no source data populated — all of {_FETCH_SOURCES} are empty")
    return next_state


def retrieval_node(state: WorkflowState) -> WorkflowState:
    """Retrieve episodic corrections relevant to the current fetched data."""
    _require(isinstance(state.get("raw_fetched_data"), dict) and bool(state.get("raw_fetched_data")),
             "retrieval", "raw_fetched_data missing — fetcher_node must run first")
    next_state: WorkflowState = dict(state)
    raw_fetched_data = state.get("raw_fetched_data") if isinstance(state.get("raw_fetched_data"), dict) else {}

    query_parts = []
    location = raw_fetched_data.get("location") if isinstance(raw_fetched_data.get("location"), dict) else {}
    location_text = str((location or {}).get("resolved_name") or "").strip()
    if location_text:
        query_parts.append(f"location={location_text}")

    calendar_events = raw_fetched_data.get("calendar_events") if isinstance(raw_fetched_data.get("calendar_events"), list) else []
    emails = raw_fetched_data.get("emails") if isinstance(raw_fetched_data.get("emails"), list) else []
    tasks = raw_fetched_data.get("tasks") if isinstance(raw_fetched_data.get("tasks"), list) else []

    for event in calendar_events[:3]:
        if isinstance(event, dict):
            query_parts.append(str(event.get("summary") or ""))
    for email in emails[:3]:
        if isinstance(email, dict):
            query_parts.append(str(email.get("subject") or ""))
    from datetime import datetime, timezone as _tz
    has_overdue = False
    for task in tasks[:3]:
        if isinstance(task, dict):
            query_parts.append(str(task.get("title") or ""))
            due = task.get("due")
            if due:
                try:
                    due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                    if due_dt < datetime.now(_tz.utc):
                        has_overdue = True
                except Exception:
                    pass
    if has_overdue:
        query_parts.append("overdue task high priority past due date")

    query = " | ".join(part for part in query_parts if part).strip()
    from memory_store import get_shared_store
    store = get_shared_store()
    if not store.vector_enabled:
        raise RuntimeError(
            "Vector backend is required for retrieval node but is unavailable. "
            f"Details: {store.backend_status().get('backend_error') or 'unknown error'}"
        )
    retrieved = store.retrieve_similar(query, top_k=5) if query else []
    next_state["retrieved_corrections"] = retrieved
    return next_state


def strategist_node(state: WorkflowState) -> WorkflowState:
    """2-level BFS ToT strategist node."""
    _require(isinstance(state.get("raw_fetched_data"), dict) and bool(state.get("raw_fetched_data")),
             "strategist", "raw_fetched_data missing — fetcher and retrieval must run first")
    _require("retrieved_corrections" in state,
             "strategist", "retrieved_corrections missing — retrieval_node must run first")
    next_state = ranking_strategist(state)
    candidates = next_state.get("candidate_rankings") or []
    if candidates:
        mcp_call("set_candidates", {"candidates_json": json.dumps(candidates)})
    return next_state


def critic_node(state: WorkflowState) -> WorkflowState:
    """Score and prune candidates via LangChain tools + CrewAI critic; sync to MCP."""
    candidates = state.get("candidate_rankings")
    _require(isinstance(candidates, list) and len(candidates) >= 1,
             "critic", "candidate_rankings is empty — strategist_node must produce at least 1 candidate")
    tot_level = state.get("tot_level") or 1
    if tot_level == 2:
        _require(isinstance(state.get("surviving_candidates"), list) and len(state.get("surviving_candidates")) >= 1,
                 "critic", "surviving_candidates missing for L2 — L1 critic must populate it")
    next_state = ranking_critic(state)
    scores = next_state.get("scores") or []
    pruning = next_state.get("pruning_decisions") or []

    for row in scores:
        cid = str(row.get("candidate_id") or "")
        if cid:
            mcp_call("update_candidate_score", {
                "candidate_id": cid,
                "scores_json": json.dumps(row),
            })
    for decision in pruning:
        cid = str(decision.get("candidate_id") or "")
        if cid and cid != "__controller__":
            mcp_call("update_pruning_decision", {
                "candidate_id": cid,
                "decision": str(decision.get("decision", "")),
                "rationale": str(decision.get("rationale", "")),
            })
    controller = next(
        (d for d in reversed(pruning) if d.get("candidate_id") == "__controller__"), {}
    )
    if controller.get("decision") == "refine":
        mcp_call("increment_refinement_round", {})

    return next_state


def synthesize_node(state: WorkflowState) -> WorkflowState:
    """Synthesize final digest output from the selected ranking."""
    candidates = state.get("candidate_rankings")
    _require(isinstance(candidates, list) and len(candidates) >= 1,
             "synthesize", "candidate_rankings is empty — critic must produce at least 1 scored candidate")
    pruning = state.get("pruning_decisions") or []
    controller = next((d for d in reversed(pruning) if isinstance(d, dict) and d.get("candidate_id") == "__controller__"), None)
    _require(controller is not None and controller.get("decision") == "proceed",
             "synthesize", "no 'proceed' decision from L2 critic — workflow routing error")
    return synthesize_digest(state)


def feedback_node(state: WorkflowState) -> WorkflowState:
    """Collect user feedback and persist it through the workflow state graph."""
    digest_output = state.get("digest_output")
    _require(isinstance(digest_output, (dict, str)) and bool(digest_output),
             "feedback", "digest_output is empty — synthesize_node must produce output before feedback")
    return user_feedback_agent(state)


def route_after_critic(state: WorkflowState) -> str:
    """Route after critic based on ToT level.

    Level-1 critic emits decision='expand' → advance tot_level to 2, re-enter strategist.
    Level-2 critic emits decision='proceed' → synthesize.
    """
    pruning = state.get("pruning_decisions") if isinstance(state.get("pruning_decisions"), list) else []
    for decision in reversed(pruning):
        if not isinstance(decision, dict):
            continue
        if str(decision.get("candidate_id") or "") != "__controller__":
            continue
        controller_decision = str(decision.get("decision") or "")
        if controller_decision == "expand":
            return "strategist_l2"
        break
    return "synthesize"


def strategist_l2_node(state: WorkflowState) -> WorkflowState:
    """Advance tot_level to 2 then run Level-2 strategist expansion."""
    surviving = state.get("surviving_candidates")
    _require(isinstance(surviving, list) and len(surviving) >= 1,
             "strategist_l2", "surviving_candidates is empty — L1 critic must select at least 1 candidate to refine")
    next_state: WorkflowState = dict(state)
    next_state["tot_level"] = 2
    return strategist_node(next_state)


def describe_workflow_graph() -> dict:
    """Return a static description of the workflow graph nodes and edges."""
    return {
        "nodes": [
            {"id": "fetcher",       "label": "Fetcher",         "description": "Fetches calendar, email, tasks, news & weather"},
            {"id": "retrieval",     "label": "Retrieval",        "description": "Retrieves episodic corrections from ChromaDB"},
            {"id": "strategist",    "label": "Strategist (L1)",  "description": "Generates 5 ToT candidate rankings via Ollama"},
            {"id": "critic",        "label": "Critic",           "description": "Scores candidates with LangChain tools + Claude coherence"},
            {"id": "strategist_l2", "label": "Strategist (L2)",  "description": "Refines top-2 survivors into 4 leaf candidates via Ollama"},
            {"id": "synthesize",    "label": "Synthesize",       "description": "Builds final digest from best-scoring candidate"},
            {"id": "feedback",      "label": "Feedback",         "description": "Captures user feedback and persists to ChromaDB"},
        ],
        "edges": [
            {"from": "START",        "to": "fetcher",       "type": "normal"},
            {"from": "fetcher",      "to": "retrieval",     "type": "normal"},
            {"from": "retrieval",    "to": "strategist",    "type": "normal"},
            {"from": "strategist",   "to": "critic",        "type": "normal"},
            {"from": "critic",       "to": "strategist_l2", "type": "conditional", "condition": "L1 → expand top-2"},
            {"from": "critic",       "to": "synthesize",    "type": "conditional", "condition": "L2 → proceed"},
            {"from": "strategist_l2","to": "critic",        "type": "normal"},
            {"from": "synthesize",   "to": "feedback",      "type": "normal"},
            {"from": "feedback",     "to": "END",           "type": "normal"},
        ],
    }


def build_workflow_graph() -> CompiledStateGraph:
    """Build workflow graph with ToT refinement loop and digest synthesis."""
    try:
        graph_module = importlib.import_module("langgraph.graph")
        END = graph_module.END
        START = graph_module.START
        StateGraph = graph_module.StateGraph
    except ImportError as exc:
        raise ImportError(
            "langgraph is required to build the workflow graph. Install with: pip install langgraph"
        ) from exc

    graph = StateGraph(WorkflowState)
    graph.add_node("fetcher", fetcher_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("strategist", strategist_node)       # Level-1 theme generation
    graph.add_node("critic", critic_node)               # Level-1 pruning OR Level-2 scoring
    graph.add_node("strategist_l2", strategist_l2_node) # Level-2 expansion
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("feedback", feedback_node)
    graph.add_edge(START, "fetcher")
    graph.add_edge("fetcher", "retrieval")
    graph.add_edge("retrieval", "strategist")
    graph.add_edge("strategist", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "strategist_l2": "strategist_l2",
            "synthesize": "synthesize",
        },
    )
    graph.add_edge("strategist_l2", "critic")           # Level-2 candidates → critic L2
    graph.add_edge("synthesize", "feedback")
    graph.add_edge("feedback", END)
    return graph.compile()


def run_workflow_digest(initial_state: WorkflowState | None = None) -> WorkflowState:
    """Run the current workflow graph through fetch, retrieval, rank, critic, and synthesis."""
    graph = build_workflow_graph()
    return graph.invoke(initial_state or {})


def run_workflow_fetch_phase(initial_state: WorkflowState | None = None) -> WorkflowState:
    """Backward-compatible alias for the full workflow runner."""
    return run_workflow_digest(initial_state)
