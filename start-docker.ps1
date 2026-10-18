$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' scripts/configure.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
docker compose up --build -d --wait
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Finance workspace: http://localhost:8787 (or FRONTEND_PORT from .env)'
