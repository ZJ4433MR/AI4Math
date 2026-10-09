param([switch]$Live)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    & $pythonPath -m pip install -r requirements.lock
    & $pythonPath -m pip install -e .
}
if ($Live) { & $pythonPath scripts/reproduce.py --live }
else { & $pythonPath scripts/reproduce.py }
if ($LASTEXITCODE -ne 0) { throw 'Reproduction failed; see diagnostics above.' }
