# cmu-agentic-ai

Daily Digest agent that gathers data from Google services, weather, and news, then synthesizes a prioritized briefing.

## Run

```bash
./run.sh
```

Or start the backend and frontend separately:

```bash
.venv312/bin/uvicorn server:app --reload
cd web && npm run dev
```

At startup, the app shows a diagnostics panel with strategist/critic model settings and episodic memory backend status.

## Setup

Bootstrap dependencies:

```bash
bash scripts/setup_claude_code.sh
```

Optional (CrewAI integration):

```bash
bash scripts/setup_claude_code.sh --with-crewai
```

Then run:

```bash
.venv312/bin/python main.py
```

And test:

```bash
.venv312/bin/python -m unittest discover -s tests -p "test_*.py"
```

## Maintenance

Reset preferences if needed:

```bash
.venv312/bin/python main.py --reset-preferences digest
```

## Module Layout

- `main.py`: application entrypoint and startup diagnostics.
- `workflow_controller.py`: LangGraph workflow assembly and execution.
- `user_interactions.py`: identity setup, digest feedback capture, and optional digest email delivery.
- `episodic_context.py`: run-context tracking and retrieval query construction from current observations.
- `memory_store.py`: episodic memory persistence/retrieval with Chroma vector backend (vector-only).
- `actions/`: tool integrations for external data sources and deterministic helper actions.
	- `location_action.py`, `time_action.py`, `weather_action.py`, `news_action.py`: location and environmental context.
	- `calendar_action.py`, `email_action.py`, `tasks_action.py`: Google Calendar/Gmail/Tasks read-write integrations.
	- `key_highlights_action.py`: attendee-email overlap analysis and follow-up task creation.
	- `daily_digest_action.py`: structured digest scaffold metadata (title, date/time, section availability).
	- `google_services.py`: shared Google OAuth/service client bootstrap and error formatting.
- `preferences.py`: local preference persistence and summarization logic.

## Notes

- Local sensitive files are intentionally ignored via `.gitignore` (for example `.env`, credentials/token files, `.memory/`, and local preference state).
- Episodic retrieval is recency-aware with stale-signal handling for older corrections.
- Episodic retrieval and writes are vector-only; vector backend unavailable is a hard error.

## Tests

Run lightweight unit tests for retrieval heuristics and memory indexing:

```bash
.venv312/bin/python -m unittest discover -s tests -p "test_*.py"
```

## Shadow Metrics Ops

Prepare the CI contract log snapshot:

```bash
.venv312/bin/python scripts/prepare_ci_shadow_log.py --source .memory/key_highlights_shadow.jsonl --output ci/key_highlights_shadow.jsonl --tail 50
```

Summarize shadow metrics and write a JSON report:

```bash
.venv312/bin/python scripts/summarize_shadow_metrics.py --log-path ci/key_highlights_shadow.jsonl --tail 50 --output-json reports/latest_shadow_metrics.json
```

Enforce quality gates locally (non-zero exit on failure):

```bash
.venv312/bin/python scripts/summarize_shadow_metrics.py --log-path ci/key_highlights_shadow.jsonl --tail 50 --min-records 10 --min-valid-rate 0.95 --max-timeout-rate 0.05 --min-promotion-pass-rate 0.70 --enforce-gates
```

## LLM Configuration

Runtime model configuration is per-agent:

- Strategist uses Ollama (`OLLAMA_MODEL`, default `llama3.1:8b`)
- Critic uses Claude (`ANTHROPIC_MODEL`, default `claude-opus-4-6`)
- `OLLAMA_BASE_URL` and `OLLAMA_NUM_CTX` tune Ollama runtime behavior
- Optional Galileo observability:
	- `GALILEO_OBSERVABILITY_ENABLED=1` enables event emission (no-op when Galileo SDK is not installed)
	- `GALILEO_INCLUDE_CONTENT=1` includes raw prompt/response content in events
	- Default behavior is metadata-only (`prompt_chars`, `response_chars`, hashes, latency, status)
