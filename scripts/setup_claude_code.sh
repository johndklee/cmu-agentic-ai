#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv312"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"

INSTALL_CREWAI="0"
for arg in "$@"; do
  case "$arg" in
    --with-crewai)
      INSTALL_CREWAI="1"
      ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/setup_claude_code.sh [--with-crewai]

Creates/uses .venv312, installs required dependencies, and prints run/test commands.

Options:
  --with-crewai   Install optional CrewAI integration package
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Creating venv at ${VENV_DIR}"
  python3.12 -m venv "$VENV_DIR"
fi

"$PIP_BIN" install --upgrade pip wheel
"$PIP_BIN" install "setuptools<82"

"$PIP_BIN" install \
  anthropic \
  chromadb \
  google-api-python-client \
  google-auth \
  google-auth-oauthlib \
  langgraph \
  python-dotenv \
  requests \
  rich \
  sentence-transformers

if [[ "$INSTALL_CREWAI" == "1" ]]; then
  "$PIP_BIN" install crewai
fi

cat <<EOF

Claude Code setup complete.

Run app:
  ${PYTHON_BIN} ${ROOT_DIR}/main.py

Run tests:
  ${PYTHON_BIN} -m unittest discover -s ${ROOT_DIR}/tests -p "test_*.py"

Optional:
  Re-run setup with --with-crewai to install CrewAI integration.
EOF
