#!/bin/zsh
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Start Ollama if not already running
if ! ollama list &>/dev/null; then
  echo "Starting Ollama..."
  ollama serve &>/tmp/ollama.log &
  sleep 3
fi

# Clear ports used by the server and MCP before starting
lsof -ti :8000 | xargs kill -9 2>/dev/null
lsof -ti :8001 | xargs kill -9 2>/dev/null

# Build frontend into web/dist so it's served by FastAPI on port 8000
cd web && npm run build && cd "$ROOT"

# Start backend (serves built frontend + API on port 8000)
.venv312/bin/uvicorn server:app --reload
