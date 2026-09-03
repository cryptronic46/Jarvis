$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Executa primeiro .\setup.ps1 -SkipModel" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== JARVIS 0.26.0 - LEGACY WAKE WORD / SMART APP CONTROL ==="
Write-Host "Sem conta, sem AccessKey e sem DLL adicional de wake word."
Write-Host ""

Write-Host "A verificar a stack de voz que ja funciona no JARVIS..."
& ".\.venv\Scripts\python.exe" -c "import sounddevice, numpy; from jarvis_core.services.stt_compat import probe_faster_whisper_pcm_import; r=probe_faster_whisper_pcm_import(); print('Wake dependencies OK - PCM STT:', r.get('status')); raise SystemExit(0 if r.get('ok') else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "A stack de voz existente nao carregou corretamente."
}

Write-Host ""
Write-Host "Motor legacy pronto. Para o motor recomendado executa .\setup_voice_v2.ps1." -ForegroundColor Green
Write-Host "Nao existe pacote KWS adicional para instalar."
Write-Host "Inicia o JARVIS e executa: /wake doctor"
