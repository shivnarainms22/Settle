# Single-port image: FastAPI serves the API and the built React app on :8000.
# Secrets are never baked in: pass them at run time, e.g. `docker run --env-file backend/.env -p 8000:8000 settle`.
# Demo logins are off in the image: set SETTLE_USERS + SETTLE_SECRET, or SETTLE_ALLOW_DEMO_USERS=1 for a local demo.
FROM node:20-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --extra moss --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev --extra moss
COPY --from=web /app/frontend/dist /app/frontend/dist
ENV SETTLE_ALLOW_DEMO_USERS=0
ENV SETTLE_DB=/data/settle.db PATH="/app/backend/.venv/bin:$PATH"
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "settle.api:app", "--host", "0.0.0.0", "--port", "8000"]
