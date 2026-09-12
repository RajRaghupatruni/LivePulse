$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$response = Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/v1/demo/reset'
Write-Host "Demo data reset: $($response.status)"
