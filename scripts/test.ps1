$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repoRoot 'backend'
Push-Location $backend
try {
  & (Join-Path $backend '.venv\Scripts\ruff.exe') check app tests alembic
  if ($LASTEXITCODE -ne 0) { throw 'Ruff reported issues.' }
  & (Join-Path $backend '.venv\Scripts\pytest.exe')
  if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
} finally { Pop-Location }
Push-Location (Join-Path $repoRoot 'web')
try {
  npm run lint
  if ($LASTEXITCODE -ne 0) { throw 'Frontend lint/typecheck failed.' }
  npm test
  if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
