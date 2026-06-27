# cmu-agentic-ai

Daily Digest agent that gathers data from Google services, weather, and news, then synthesizes a prioritized briefing using a Tree-of-Thought ranking pipeline with local and cloud LLMs.

## Prerequisites

Install these before cloning:

| Tool | Version | Install |
|---|---|---|
| Python | 3.12 | [python.org](https://www.python.org/downloads/) or `brew install python@3.12` |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) or `brew install node` |
| Ollama | latest | [ollama.com](https://ollama.com/) or `brew install ollama` |

After installing Ollama, pull the recommended model:

```bash
ollama pull qwen3:8b
```

## Quickstart

```bash
# 1. Clone the repo
git clone https://github.com/johndklee/cmu-agentic-ai.git
cd cmu-agentic-ai

# 2. Install Python dependencies
bash scripts/setup_claude_code.sh

# 3. Install Node dependencies
cd web && npm install && cd ..

# 4. Create .env (see Environment Variables section below)
cp .env.example .env   # then fill in your keys

# 5. Set up Google credentials (see Google Services Setup section below)

# 6. Run
./run.sh
```

The app runs at **http://localhost:8000**. At startup it shows a diagnostics panel confirming all services are connected.

## Run

```bash
./run.sh
```

This starts Ollama (if not already running), builds the frontend, and launches the FastAPI backend on port 8000.

Or start backend and frontend separately in dev mode:

```bash
.venv312/bin/uvicorn server:app --reload   # backend on :8000
cd web && npm run dev                       # frontend on :5173
```

## Maintenance

Reset preferences if needed:

```bash
.venv312/bin/python main.py --reset-preferences digest
```

## Tests

```bash
.venv312/bin/python -m unittest discover -s tests -p "test_*.py"
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

Copy `.env.example` to `.env` and fill in your keys. This file is in `.gitignore` and will never be committed.

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | Claude API key for the Ranking Critic — get at [console.anthropic.com](https://console.anthropic.com) |
| `OLLAMA_MODEL` | **Yes** | Local model for the Ranking Strategist — e.g. `qwen3:8b` |
| `OLLAMA_BASE_URL` | No | Ollama server URL (default: `http://localhost:11434`) |
| `OLLAMA_NUM_CTX` | No | Context window override (uses model default if not set) |
| `HF_TOKEN` | No | HuggingFace token for higher download rate limits — get at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `GALILEO_OBSERVABILITY_ENABLED` | No | Set to `1` to emit LLM trace events to Galileo |
| `GALILEO_API_KEY` | No | Required when Galileo observability is enabled |
| `GALILEO_CONSOLE_URL` | No | Your Galileo project URL |
| `GALILEO_INCLUDE_CONTENT` | No | Set to `1` to include raw prompt/response in Galileo events |

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

- Local sensitive files are intentionally ignored via `.gitignore` (`.env`, credentials/token files, `.memory/`, and local preference state).
- Episodic retrieval is recency-aware with stale-signal handling for older corrections.
- Episodic retrieval and writes are vector-only; vector backend unavailable is a hard error.
- `run.sh` requires macOS or Linux (zsh).

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
