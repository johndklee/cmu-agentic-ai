---
name: run-mainpy
user-invocable: true
description: "Run the daily digest web app (FastAPI backend + React frontend). Use when the user asks to run the app, launch the server, or validate startup/runtime behavior."
---

# Run the Daily Digest Web App

## Backend (FastAPI)

```bash
.venv312/bin/uvicorn server:app --reload
```

Runs on http://localhost:8000. API endpoints:
- `GET  /api/health` — startup diagnostics
- `POST /api/digest` — generate digest (triggers LangGraph workflow)
- `POST /api/feedback` — submit satisfaction + improvement note
- `GET  /api/preferences` — read user preferences
- `POST /api/preferences` — update user preferences

## Frontend (React/Vite dev server)

```bash
cd web && npm run dev
```

Runs on http://localhost:5173. Proxies `/api` requests to the FastAPI backend.

## With live Google API probes

```bash
GOOGLE_DIAGNOSTICS_LIVE=1 .venv312/bin/uvicorn server:app --reload
```

## CLI flags (backend)

- `--reset-preferences all|digest`: Reset saved preferences and exit (run via `main.py` directly)
- `--galileo-observability`: Enable Galileo observability events
- `--galileo-include-content`: Include raw prompt/response in Galileo events (requires `--galileo-observability`)

## Notes

- Both backend and frontend must be running for the app to work in dev mode.
- For production, run `cd web && npm run build` first — FastAPI serves the built `web/dist/` automatically.
- If startup fails, capture the traceback and report the first actionable root cause.
- For quick validation after fixes, run:

```bash
.venv312/bin/python -m unittest discover -s tests -p "test_*.py"
```
