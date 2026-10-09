$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (!(Test-Path ".venv")) { py -3 -m venv .venv }
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
$env:HROT_MODE = "demo"
Write-Host "HROT AirTrust at http://127.0.0.1:8765 (DEMO / localhost only)" -ForegroundColor Cyan
Start-Process "http://127.0.0.1:8765"
& $python -m uvicorn server:app --host 127.0.0.1 --port 8765
