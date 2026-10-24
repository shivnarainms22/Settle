# One command, one port: build the frontend, then serve it and the API from FastAPI on http://localhost:8000.
# Keys are read from backend/.env (see backend/.env.example); without them Settle runs fully offline.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is required: https://docs.astral.sh/uv/" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm (Node 18+) is required" }
Push-Location frontend
if (-not (Test-Path node_modules)) { npm ci; if ($LASTEXITCODE) { throw "npm ci failed" } }
npm run build --silent; if ($LASTEXITCODE) { throw "frontend build failed" }
Pop-Location
Set-Location backend
uv sync --extra moss --quiet; if ($LASTEXITCODE) { throw "uv sync failed" }
$port = if ($env:PORT) { $env:PORT } else { "8000" }
Write-Host "Settle on http://localhost:$port  (demo logins: dana / sam / vic, password: demo)"
uv run uvicorn settle.api:app --host 127.0.0.1 --port $port
