$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path (Join-Path $repoRoot '.env'))) {
  Copy-Item (Join-Path $repoRoot '.env.example') (Join-Path $repoRoot '.env')
}

docker compose -f (Join-Path $repoRoot 'docker-compose.yml') up -d --wait postgres redpanda
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed to start PostgreSQL and Redpanda.' }

$backend = Join-Path $repoRoot 'backend'
if (-not (Test-Path (Join-Path $backend '.venv'))) { python -m venv (Join-Path $backend '.venv') }
Push-Location $backend
try {
  & (Join-Path $backend '.venv\Scripts\python.exe') -m pip install -e '.[dev]'
  if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
} finally { Pop-Location }

Push-Location (Join-Path $repoRoot 'web')
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
} finally { Pop-Location }

Write-Host 'Bootstrap complete. Start backend with scripts/dev.ps1 and frontend with: cd web; npm run dev'
