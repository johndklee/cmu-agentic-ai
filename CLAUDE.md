# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands use the venv Python interpreter at `.venv312/bin/python`.

**Run the backend (FastAPI):**
```bash
.venv312/bin/uvicorn server:app --reload
```

**Run with live Google API diagnostics** (Calendar/Gmail/Tasks probes; disabled by default):
```bash
GOOGLE_DIAGNOSTICS_LIVE=1 .venv312/bin/uvicorn server:app --reload
```

**Run the frontend (React/Vite dev server):**
```bash
cd web && npm run dev
```

**Build the frontend for production:**
```bash
cd web && npm run build
```

**Run tests:**
```bash
.venv312/bin/python -m unittest discover -s tests -p "test_*.py"
```

**Run a single test file:**
```bash
.venv312/bin/python -m unittest tests.test_memory_store
```

**Prepare CI shadow log snapshot:**
```bash
.venv312/bin/python scripts/prepare_ci_shadow_log.py --source .memory/key_highlights_shadow.jsonl --output ci/key_highlights_shadow.jsonl --tail 50
```

**Check shadow metrics quality gates locally:**
```bash
.venv312/bin/python scripts/summarize_shadow_metrics.py --log-path ci/key_highlights_shadow.jsonl --tail 50 --min-records 10 --min-valid-rate 0.95 --max-timeout-rate 0.05 --min-promotion-pass-rate 0.70 --enforce-gates
```

**Runtime flags:**
- `--reset-preferences all|digest`: Reset saved preferences and exit
- `--galileo-observability`: Enable Galileo observability to emit observability events
- `--galileo-include-content`: Include raw prompt/response in Galileo observability events (requires `--galileo-observability`)

## LLM Configuration

Provider and model are resolved from preferences then environment variables:
- `LLM_PROVIDER`: `ollama` (default) or `anthropic`
- `LLM_MODEL`: explicit model override
- `ANTHROPIC_MODEL` / `OLLAMA_MODEL`: provider-specific defaults
- Default model: `llama3.1:8b` on Ollama
- `OLLAMA_BASE_URL`: Ollama endpoint (default `http://localhost:11434`)
- `OLLAMA_NUM_CTX`: optional context window override
- `OLLAMA_REQUEST_TIMEOUT_SECONDS`: request timeout (default 120)
- `GALILEO_OBSERVABILITY_ENABLED`: set to `1` to emit observability events (best-effort no-op if SDK is missing)
- `GALILEO_INCLUDE_CONTENT`: set to `1` to include raw prompt/response in events; default is metadata-only

## Architecture

### LangGraph Workflow (`main.py` + `workflow_controller.py`)

The runtime is graph-only. `main.py` calls `run_workflow_digest()` and renders `digest_output`; there is no ReAct fallback path.

Graph flow:
- `START -> fetcher -> retrieval -> strategist -> critic`
- Critic conditional routing: `strategist` (refine) or `synthesize`
- `synthesize -> feedback -> END`

`workflow_controller.py:build_workflow_graph()` hard-requires `langgraph`; missing `langgraph` is treated as a runtime error.

### Tool Actions (`actions/`)

Action modules expose `run_*_action()` functions consumed by workflow agents (for example `fetcher_agent.py`):
- `location_action.py`: IP-based location with session-level preference override
- `time_action.py`, `weather_action.py`, `news_action.py`: external API calls
- `calendar_action.py`, `email_action.py`, `tasks_action.py`: Google API read/write via shared OAuth client in `google_services.py`
- `key_highlights_action.py`: attendee-email overlap detection; creates Google Tasks follow-ups
- `daily_digest_action.py`: builds structured JSON metadata (title, date, time, location) used by digest rendering

### Digest Rendering (`digest_rendering.py`)

`build_digest_payload(observations)` normalizes raw action observations into a canonical dict. `render_terminal_digest()` and `render_email_digest_markup()` produce Rich-markup output for terminal and email respectively. This deterministic path is the fallback when the LLM produces invalid output.

### Episodic Memory (`memory_store.py` + `episodic_context.py`)

`EpisodicMemoryStore` persists user feedback corrections in a Chroma vector DB at `.memory/chroma/`. Retrieval and writes are vector-only; if vector backend is unavailable, both retrieval and writes raise a hard error. Records are weighted by recency (full weight ≤30 days, 0.75x ≤60 days, 0.55x older). Items older than 60 days are flagged stale.

`episodic_context.py` builds the retrieval query from current-run signals (attendees, senders, event contexts, urgency markers) and selects the most relevant correction type scope before querying.

### Two-Agent Contract (Shadow Mode)

`key_highlights_agent.py` implements the shadow-mode Agent B wrapper for key highlights. The contract (`docs/two-agent-contract.md`) defines three phases:
- **Phase 0** (done): Contract as documentation only
- **Phase 1** (current): `run_key_highlights_shadow()` generates a candidate output, `validate_agent_b_output()` checks the schema, metrics are logged to `.memory/key_highlights_shadow.jsonl`
- **Phase 2**: Adopt Agent B output when `should_promote_shadow_result()` gates pass (schema valid, confidence medium/high, overlap ≥0.6, ordering changes ≤2, non-empty)

The shadow call runs with a 2.5s timeout in a thread pool; timeout routes to existing deterministic highlights.

### CI / Shadow Metrics Gate

`.github/workflows/shadow-metrics-gate.yml` runs on every PR. It calls `scripts/prepare_ci_shadow_log.py` to copy the committed `ci/key_highlights_shadow.jsonl` snapshot, then enforces quality gates via `scripts/summarize_shadow_metrics.py --enforce-gates`. The CI contract file must be refreshed locally before PRs that change shadow behavior. Threshold raise policy (detailed in `docs/two-agent-contract.md`) requires 2 consecutive passing weekly reports before tightening any single gate threshold.

### Preferences and State

`preferences.py` manages persisted preferences in local Chroma collections (semantic/procedural/runtime) including identity, VIP emails, digest feedback history, and LLM provider settings. `user_interactions.py` handles the interactive prompts at startup and post-digest feedback capture.
