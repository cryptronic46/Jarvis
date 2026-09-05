param(
    [string]$CorePath = "G:\JARVIS",
    [int]$Port = 8765,
    [switch]$Visible
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bridge = Join-Path $Root "bridge\jarvis_bridge.py"

$Python = Join-Path $CorePath ".venv\Scripts\python.exe"
$PythonW = Join-Path $CorePath ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Não encontrei o Python do JARVIS em: $Python" -ForegroundColor Red
    Write-Host "Confirma que o Core está em G:\JARVIS ou usa: .\start_bridge.ps1 -CorePath 'CAMINHO'" -ForegroundColor Yellow
    exit 1
}

# Don't open a duplicate bridge.
$Health = "http://127.0.0.1:$Port/api/health"
try {
    $Existing = Invoke-RestMethod -Uri $Health -TimeoutSec 1
    if ($Existing.ok) {
        Write-Host "JARVIS Wallpaper Bridge já está ativo em $Health" -ForegroundColor Green
        exit 0
    }
} catch {}

$Args = @(
    "`"$Bridge`"",
    "--core", "`"$CorePath`"",
    "--host", "127.0.0.1",
    "--port", "$Port"
)

if ($Visible) {
    & $Python @Args
    exit $LASTEXITCODE
}

if (Test-Path $PythonW) {
    Start-Process -FilePath $PythonW -ArgumentList $Args -WindowStyle Hidden
} else {
    Start-Process -FilePath $Python -ArgumentList $Args -WindowStyle Hidden
}

Start-Sleep -Milliseconds 900
try {
    $Result = Invoke-RestMethod -Uri $Health -TimeoutSec 2
    if ($Result.ok) {
        Write-Host "JARVIS Wallpaper Bridge ONLINE" -ForegroundColor Cyan
        Write-Host "Preview: http://127.0.0.1:$Port/" -ForegroundColor Cyan
        exit 0
    }
} catch {}

Write-Host "O bridge foi iniciado, mas ainda não respondeu em $Health." -ForegroundColor Yellow
Write-Host "Para diagnóstico: .\start_bridge.ps1 -Visible" -ForegroundColor Yellow
