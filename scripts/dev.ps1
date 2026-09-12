$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repoRoot 'backend'

docker compose -f (Join-Path $repoRoot 'docker-compose.yml') up -d postgres redpanda
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed.' }
Push-Location $backend
try {
  & (Join-Path $backend '.venv\Scripts\alembic.exe') upgrade head
  if ($LASTEXITCODE -ne 0) { throw 'Alembic migration failed.' }
  & (Join-Path $backend '.venv\Scripts\uvicorn.exe') app.main:app --host 0.0.0.0 --port 8000
} finally { Pop-Location }
