"""Optional CrewAI integration for ranking strategist and critic agents."""

import importlib.util
import json
import os
from typing import Any

from llm_client import ANTHROPIC_DEFAULT_MODEL, OLLAMA_DEFAULT_MODEL
from workflow_state import WorkflowState

CREWAI_AVAILABLE = importlib.util.find_spec("crewai") is not None


def _import_crewai_types():
    """Import CrewAI types; raises RuntimeError if unavailable."""
    if not CREWAI_AVAILABLE:
        raise RuntimeError(
            "CrewAI is required but not installed. Install with: pip install crewai"
        )
    from crewai import Agent, Crew, Process, Task
    try:
        from crewai import LLM
    except ImportError:
        LLM = None
    return Agent, Crew, Process, Task, LLM


def _resolve_ollama_model() -> str:
    return (
        os.getenv("OLLAMA_MODEL", "").strip()
        or OLLAMA_DEFAULT_MODEL
    )


def _resolve_anthropic_model() -> str:
    return (
        os.getenv("ANTHROPIC_MODEL", "").strip()
        or ANTHROPIC_DEFAULT_MODEL
    )


def _build_ollama_llm(llm_type):
    """Build a CrewAI LLM for Ollama with the provider-prefixed model name."""
    model = _resolve_ollama_model()
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
    prefixed = f"ollama/{model}" if not model.startswith("ollama/") else model
    if llm_type is not None:
        try:
            return llm_type(model=prefixed, base_url=base_url, extra_body={"think": False, "format": "json"})
        except Exception:
            try:
                return llm_type(model=prefixed, base_url=base_url)
            except Exception:
                pass
    return prefixed


def _build_anthropic_llm(llm_type):
    """Build a CrewAI LLM for Anthropic with the provider-prefixed model name."""
    model = _resolve_anthropic_model()
    prefixed = f"anthropic/{model}" if not model.startswith("anthropic/") else model
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if llm_type is not None:
        try:
            return llm_type(model=prefixed, api_key=api_key) if api_key else llm_type(model=prefixed)
        except Exception:
            pass
    return prefixed


def _extract_text(result: object) -> str:
    if result is None:
        return ""
    for attr in ("raw", "output", "final_output", "text"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    if isinstance(result, str):
        return result
    return str(result)


def list_agents() -> list[dict]:
    """Return a description of every declared CrewAI agent and its backing LLM."""
    ollama_model = _resolve_ollama_model()
    anthropic_model = _resolve_anthropic_model()
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
    return [
        {
            "role": "Ranking Strategist",
            "provider": "ollama",
            "model": ollama_model,
            "endpoint": ollama_url,
            "purpose": "Generates 5 ToT candidate rankings from fetched data (L1) and refines top 2 (L2)",
        },
        {
            "role": "Ranking Critic",
            "provider": "anthropic",
            "model": anthropic_model,
            "endpoint": "api.anthropic.com",
            "purpose": "Scores ranking coherence; receives only sanitized item_id/source/priority",
        },
    ]


def _build_agents():
    Agent, _Crew, _Process, _Task, LLM = _import_crewai_types()

    strategist = Agent(
        role="Ranking Strategist",
        goal="generate candidate rankings from fetched digest data",
        backstory="You design five Tree-of-Thought candidate rankings for a daily digest using only provided state.",
        llm=_build_ollama_llm(LLM),
        allow_delegation=False,
        verbose=False,
    )
    critic = Agent(
        role="Ranking Critic",
        goal="evaluate ranking coherence for digest candidates",
        backstory="You score ranking coherence and provide a concise JSON coherence assessment.",
        llm=_build_anthropic_llm(LLM),
        allow_delegation=False,
        verbose=False,
    )
    return strategist, critic, _Crew, _Process, _Task


def _build_strategist_crew(task_description: str):
    strategist, critic, Crew, Process, Task = _build_agents()
    task = Task(
        description="/no_think\n" + task_description,
        expected_output="A JSON array with exactly 5 candidate ranking objects.",
        agent=strategist,
    )
    return Crew(agents=[strategist, critic], tasks=[task], process=Process.sequential, verbose=False)


def _build_critic_crew(task_description: str, use_ollama: bool = False):
    Agent, _Crew, _Process, _Task, LLM = _import_crewai_types()
    llm = _build_ollama_llm(LLM) if use_ollama else _build_anthropic_llm(LLM)
    critic = Agent(
        role="Ranking Critic",
        goal="evaluate ranking coherence for digest candidates",
        backstory="You score ranking coherence and provide a concise JSON coherence assessment.",
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )
    task = _Task(
        description=task_description,
        expected_output='Strict JSON only: {"coherence": 0..1, "notes": "short reason"}.',
        agent=critic,
    )
    return _Crew(agents=[critic], tasks=[task], process=_Process.sequential, verbose=False)


def _load_ranking_strategist_helpers():
    from ranking_strategist import _build_prompt, _build_rankable_items, _extract_json_array, _fallback_candidates, _validate_candidates

    return _build_prompt, _build_rankable_items, _extract_json_array, _fallback_candidates, _validate_candidates


def _load_ranking_critic_helpers():
    from ranking_critic import _coherence_score_with_claude

    return _coherence_score_with_claude


def run_crewai_ranking_strategist(state: WorkflowState, min_highlights: int = 5) -> list[dict[str, Any]]:
    """Use CrewAI strategist agent to generate five candidate rankings."""
    build_prompt, build_rankable_items, extract_json_array, _fallback_candidates, validate_candidates = _load_ranking_strategist_helpers()
    raw_fetched_data = state.get("raw_fetched_data") or {}
    corrections = state.get("retrieved_corrections") or []
    items = build_rankable_items(raw_fetched_data if isinstance(raw_fetched_data, dict) else {})
    valid_item_ids = {item["item_id"] for item in items}
    crew = _build_strategist_crew(build_prompt(items, corrections if isinstance(corrections, list) else [], min_highlights=min_highlights))
    result = crew.kickoff()
    text = _extract_text(result)
    print(f"[strategist] raw output length={len(text)} preview={text[:300]!r}")
    try:
        parsed = extract_json_array(text)
    except Exception as e:
        print(f"[strategist] JSON parse failed: {e}")
        return []
    candidates = validate_candidates(parsed, valid_item_ids)
    print(f"[strategist] valid_item_ids={valid_item_ids}")
    print(f"[strategist] candidates after validation: {len(candidates)}, ranking sizes: {[len(c.get('ranking', [])) for c in candidates]}")
    return candidates


def run_crewai_ranking_critic(candidate: dict[str, Any]) -> tuple[float, str]:
    """Evaluate ranking coherence via direct LLM call (no CrewAI crew overhead).

    Tries Anthropic (Claude) first; falls back to Ollama if unavailable.
    Returns (coherence_score, llm_label).
    """
    import re as _re
    from llm_client import _generate_with_anthropic, _generate_with_ollama

    sanitized = [
        {
            "item_id": str(entry.get("item_id") or ""),
            "source": str(entry.get("source") or ""),
            "priority": str(entry.get("priority") or ""),
        }
        for entry in (candidate.get("ranking") or [])
        if isinstance(entry, dict)
    ]
    prompt = (
        "Evaluate only coherence of ranking structure and priority choices.\n"
        'Return strict JSON only: {"coherence": <float 0..1>, "notes": "<short reason>"}.\n'
        f"Candidate ranking:\n{json.dumps(sanitized, ensure_ascii=True)}\n"
    )

    def _parse(text: str) -> float:
        text = text.strip()
        match = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
        if match:
            text = match.group(1).strip()
        if not text.startswith("{"):
            obj_match = _re.search(r"\{.*\}", text, _re.DOTALL)
            if obj_match:
                text = obj_match.group(0).strip()
        parsed = json.loads(text)
        return max(0.0, min(1.0, float(parsed.get("coherence", 0.0))))

    try:
        model = _resolve_anthropic_model()
        text = _generate_with_anthropic(prompt, model)
        return _parse(text), f"Claude ({model})"
    except Exception as anthropic_err:
        print(f"⚠️  Anthropic critic unavailable ({anthropic_err}), falling back to Ollama.")
        model = _resolve_ollama_model()
        text = _generate_with_ollama(prompt, model)
        return _parse(text), f"Ollama ({model}) [Claude fallback]"
