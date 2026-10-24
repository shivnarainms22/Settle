#!/usr/bin/env bash
# Done gate: backend tests + lint + frontend tests + build. Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")"
(cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run python -m settle.verify --offline)
(cd frontend && npm run test --silent && npm run build --silent)
echo "DONE GATE: PASS"
