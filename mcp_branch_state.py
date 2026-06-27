"""MCP server for ToT branch state — shared context across agents during a digest run."""

import asyncio
import json
import threading
from typing import Any

from fastmcp import FastMCP

# Port assigned at startup — set by start_mcp_server_background, read by mcp_call().
_mcp_port: int | None = None

mcp = FastMCP("tot-branch-state")

_lock = threading.Lock()
_state: dict[str, Any] = {
    "candidates": [],
    "surviving_candidates": [],
    "scores": {},
    "pruning_decisions": {},
    "tot_level": 1,
}


def reset_branch_state() -> None:
    """Reset all branch state for a new digest run."""
    with _lock:
        _state["candidates"] = []
        _state["surviving_candidates"] = []
        _state["scores"] = {}
        _state["pruning_decisions"] = {}
        _state["tot_level"] = 1


@mcp.tool()
def get_branch_state() -> str:
    """Return the current ToT branch state as JSON.

    Returns all candidates, scores, pruning decisions, and the current
    refinement round number.
    """
    with _lock:
        return json.dumps(_state)


@mcp.tool()
def set_candidates(candidates_json: str) -> str:
    """Store the current set of candidate rankings.

    Args:
        candidates_json: JSON array of candidate ranking dicts.

    Returns:
        Confirmation message.
    """
    candidates = json.loads(candidates_json)
    with _lock:
        _state["candidates"] = candidates
    return f"Stored {len(candidates)} candidates."


@mcp.tool()
def update_candidate_score(candidate_id: str, scores_json: str) -> str:
    """Write scores for a single candidate branch.

    Args:
        candidate_id: The candidate's identifier string.
        scores_json: JSON dict with keys meeting_proximity, vip_alignment,
                     episodic_consistency, coherence, total.

    Returns:
        Confirmation message.
    """
    scores = json.loads(scores_json)
    with _lock:
        _state["scores"][candidate_id] = scores
    return f"Updated scores for {candidate_id}."


@mcp.tool()
def update_pruning_decision(candidate_id: str, decision: str, rationale: str) -> str:
    """Record a keep/prune decision for a candidate branch.

    Args:
        candidate_id: The candidate's identifier string.
        decision: 'keep' or 'prune'.
        rationale: Human-readable reason for the decision.

    Returns:
        Confirmation message.
    """
    with _lock:
        _state["pruning_decisions"][candidate_id] = {
            "decision": decision,
            "rationale": rationale,
        }
    return f"Pruning decision '{decision}' recorded for {candidate_id}."


@mcp.tool()
def get_refinement_round() -> int:
    """Return the current ToT refinement round number (0-indexed)."""
    with _lock:
        return int(_state["refinement_round"])


@mcp.tool()
def increment_refinement_round() -> int:
    """Advance the refinement round counter and return the new value."""
    with _lock:
        _state["refinement_round"] += 1
        return int(_state["refinement_round"])


def _find_free_port(start: int = 8001, attempts: int = 10) -> int:
    """Return the first free TCP port starting from start."""
    import socket
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}–{start + attempts - 1}")


def start_mcp_server_background(host: str = "127.0.0.1", port: int = 8001) -> threading.Thread:
    """Start the MCP server in a daemon thread on the given port."""
    global _mcp_port
    _mcp_port = port
    thread = threading.Thread(
        target=mcp.run,
        kwargs={"transport": "sse", "host": host, "port": port},
        daemon=True,
        name="mcp-branch-state",
    )
    thread.start()
    return thread


async def _async_mcp_call(tool_name: str, arguments: dict) -> Any:
    """Call an MCP tool on the local SSE server and return the result."""
    from mcp.client.sse import sse_client
    from mcp import ClientSession
    if _mcp_port is None:
        raise RuntimeError("MCP server not started — _mcp_port is None.")
    url = f"http://127.0.0.1:{_mcp_port}/sse"
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
            if result.content:
                return result.content[0].text
            return None


def mcp_call(tool_name: str, arguments: dict | None = None) -> Any:
    """Synchronous wrapper around _async_mcp_call for use in non-async agent code."""
    return asyncio.run(_async_mcp_call(tool_name, arguments or {}))
