param([string]$Destination = "G:\JARVIS")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $Destination
$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Executa primeiro .\setup.ps1 -SkipModel" }
Write-Host "=== JARVIS 0.27.8 - FULL SYSTEM VALIDATION ===" -ForegroundColor Cyan
Write-Host "[1/3] Integridade integral da release..."
& ".\verify_release.ps1" -Destination $Destination
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "[2/3] Suite completa do Core..."
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "[3/3] Runtime real: native/audio/STT/local-brain/router/security..."
& $Python -m jarvis_core.services.full_validation
if ($LASTEXITCODE -ne 0) {
    Write-Host "FULL VALIDATION: FALHOU - consulta logs\full_validation_0277.json" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "FULL VALIDATION: OK" -ForegroundColor Green
Write-Host "Relatorio: logs\full_validation_0277.json"
