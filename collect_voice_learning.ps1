param(
    [int]$Positive = 8,
    [int]$Negative = 8,
    [double]$Seconds = 2.0,
    [string]$DeviceName = "GENERAL WEBCAM"
)
$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Python da JARVIS não encontrado." }
Write-Host "Fecha o JARVIS antes desta recolha para libertar o microfone." -ForegroundColor Yellow
& $Python -m jarvis_core.learning.collect_voice_samples --positive $Positive --negative $Negative --seconds $Seconds --device-name $DeviceName
if ($LASTEXITCODE -ne 0) { throw "Falhou a recolha de amostras." }
Write-Host "Amostras guardadas em memory\voice_learning." -ForegroundColor Green
