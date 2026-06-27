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

## Environment Variables

Create a `.env` file in the project root before running the app. This file is in `.gitignore` and will never be committed.

```bash
# ── Required ────────────────────────────────────────────────────────────────

# Anthropic API key — used by the Ranking Critic agent (Claude)
# Get yours at https://console.anthropic.com
ANTHROPIC_API_KEY=sk-ant-...

# ── LLM (Ollama) ────────────────────────────────────────────────────────────

# Ollama model for the Ranking Strategist (runs locally)
# Default: llama3.1:8b  Recommended: qwen3:8b (128K context)
# Pull with: ollama pull qwen3:8b
OLLAMA_MODEL=qwen3:8b

# Ollama server URL (default shown — change if running on a different host)
# OLLAMA_BASE_URL=http://localhost:11434

# Optional context window override (Ollama uses model default if not set)
# OLLAMA_NUM_CTX=32768

# ── HuggingFace ─────────────────────────────────────────────────────────────

# HuggingFace token — optional, lifts download rate limits for embedding model
# The model (sentence-transformers/all-MiniLM-L6-v2) is public; token not required after first download
# Get yours at https://huggingface.co/settings/tokens (Read access)
# HF_TOKEN=hf_...

# ── Galileo Observability (optional) ────────────────────────────────────────

# Enable Galileo observability to emit LLM trace events
# GALILEO_OBSERVABILITY_ENABLED=1

# Galileo API key and console URL — required when observability is enabled
# GALILEO_API_KEY=...
# GALILEO_CONSOLE_URL=https://app.galileo.ai/...

# Include raw prompt/response content in Galileo events (default: metadata only)
# GALILEO_INCLUDE_CONTENT=1
```

## Google Services Setup

The agent reads Gmail, Google Calendar, and Google Tasks via OAuth 2.0. Setup is one-time.

**1. Create a Google Cloud Project**
- Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project

**2. Enable the APIs**
- Go to **APIs & Services → Library** and enable:
  - Gmail API
  - Google Calendar API
  - Tasks API

**3. Create OAuth 2.0 Credentials**
- Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
- If prompted, configure the OAuth consent screen first:
  - User type: **External**
  - Add your Google account email as a test user
- Application type: **Desktop app**
- Click **Create** then **Download JSON**
- Rename the downloaded file to `credentials.json` and place it in the project root

**4. Authenticate**
- Run the app — a browser window will open asking you to sign in with Google
- After approving, `token_google.json` is saved automatically
- Subsequent runs authenticate silently with no browser prompt

Both `credentials.json` and `token_google.json` are in `.gitignore` and will never be committed.

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
