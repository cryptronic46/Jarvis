$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Python da JARVIS não encontrado: $Python" }

Write-Host "=== JARVIS APP CONTROL DOCTOR ===" -ForegroundColor Cyan
Write-Host "O diagnóstico usa os eventos CodeIntegrity/AppLocker e preserva o histórico de bloqueios."
Write-Host ""
Write-Host "Bloqueios recentes relacionados com ${PSScriptRoot}:" -ForegroundColor Cyan
& $Python -c "from jarvis_core.services.windows_block_audit import audit_windows_blocked_files,format_windows_block_audit; print(format_windows_block_audit(audit_windows_blocked_files(), detail='full'))"
if ($LASTEXITCODE -ne 0) { throw "Falhou a leitura dos eventos CodeIntegrity/AppLocker." }

Write-Host ""
Write-Host "Este diagnóstico é read-only: não desativa Smart App Control, WDAC ou AppLocker." -ForegroundColor Green
