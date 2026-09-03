param(
    [string]$Destination = "G:\JARVIS-Wallpaper",
    [string]$CorePath = "G:\JARVIS"
)

$ErrorActionPreference = "Stop"
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path (Join-Path $CorePath ".venv\Scripts\python.exe"))) {
    Write-Host "Core JARVIS não encontrado em $CorePath." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$Items = @(
    "wallpaper",
    "bridge",
    "start_bridge.ps1",
    "stop_bridge.ps1",
    "install_autostart.ps1",
    "remove_autostart.ps1",
    "README.md"
)

foreach ($Item in $Items) {
    $From = Join-Path $Source $Item
    $To = Join-Path $Destination $Item
    if (Test-Path $From) {
        if ((Get-Item $From).PSIsContainer) {
            Copy-Item $From $To -Recurse -Force
        } else {
            Copy-Item $From $To -Force
        }
    }
}

Write-Host ""
Write-Host "JARVIS Live Wallpaper instalado em $Destination" -ForegroundColor Cyan
Write-Host ""
Write-Host "A iniciar bridge..." -ForegroundColor Cyan
& (Join-Path $Destination "start_bridge.ps1") -CorePath $CorePath

Write-Host ""
Write-Host "Para iniciar automaticamente com o Windows:" -ForegroundColor Yellow
Write-Host "cd $Destination"
Write-Host ".\install_autostart.ps1"
Write-Host ""
Write-Host "Wallpaper Engine:" -ForegroundColor Yellow
Write-Host "Arrasta este ficheiro para 'Create Wallpaper':"
Write-Host (Join-Path $Destination "wallpaper\index.html")
