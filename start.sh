#!/usr/bin/env bash
# One command, one port: build the frontend, then serve it and the API from FastAPI on http://localhost:8000.
# Keys are read from backend/.env (see backend/.env.example); without them Settle runs fully offline.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
command -v npm >/dev/null || { echo "npm (Node 18+) is required" >&2; exit 1; }
(cd frontend && { [ -d node_modules ] || npm ci; } && npm run build --silent)
cd backend
uv sync --extra moss --quiet
echo "Settle on http://localhost:${PORT:-8000}  (demo logins: dana / sam / vic, password: demo)"
exec uv run uvicorn settle.api:app --host 127.0.0.1 --port "${PORT:-8000}"
