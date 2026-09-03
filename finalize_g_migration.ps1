param(
    [string]$OldCore = "C:\JARVIS",
    [string]$Destination = "G:\JARVIS",
    [switch]$RemoveOldCore,
    [switch]$RemoveOldWallpaper,
    [switch]$RemoveOldWallpaperEngine
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Fail([string]$Message) { Write-Host "ERRO: $Message" -ForegroundColor Red; exit 1 }

if ([System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') -ine [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')) {
    Fail "Executa este script a partir de $Destination."
}
if (-not (Test-Path -LiteralPath '.\.venv\Scripts\python.exe' -PathType Leaf)) { Fail 'A nova .venv em G: ainda nao existe.' }
if (-not (Test-Path -LiteralPath '.\memory\migration_g.json' -PathType Leaf)) { Fail 'Nao encontrei memory\migration_g.json.' }

Write-Host 'A validar release em G:...' -ForegroundColor Cyan
& '.\verify_release.ps1' -Destination $Destination
if ($LASTEXITCODE -ne 0) { Fail 'verify_release.ps1 falhou.' }

Write-Host 'A validar schema/configuracao...' -ForegroundColor Cyan
& '.\.venv\Scripts\python.exe' -c "from jarvis_core.core.config import Settings; r=Settings.ensure_file_schema(); s=Settings.load(); assert s.voice_v2_wake_threshold >= 0.62; assert s.voice_v2_wake_strong_threshold >= 0.82; print(r); print('Wallpaper:', s.desktop_wallpaper_root)"
if ($LASTEXITCODE -ne 0) { Fail 'Schema/configuracao nao passou validacao.' }

$report = Get-Content -LiteralPath '.\memory\migration_g.json' -Raw | ConvertFrom-Json

if ($RemoveOldWallpaper -and $report.wallpaper_source -and (Test-Path -LiteralPath $report.wallpaper_source)) {
    $dest = [string]$report.wallpaper_destination
    if (-not (Test-Path -LiteralPath $dest -PathType Container)) { Fail 'Wallpaper de destino nao existe; nao removi a origem.' }
    Remove-Item -LiteralPath $report.wallpaper_source -Recurse -Force
    Write-Host "Wallpaper antigo removido: $($report.wallpaper_source)" -ForegroundColor Green
}

if ($RemoveOldWallpaperEngine -and $report.wallpaper_engine_source) {
    $oldEngineExe = [string]$report.wallpaper_engine_source
    $newEngineExe = [string]$report.wallpaper_engine_destination
    if (-not $newEngineExe) {
        Fail 'Nao existe Wallpaper Engine standalone migrado para G:; nao removi a origem.'
    }
    if (-not (Test-Path -LiteralPath $newEngineExe -PathType Leaf)) {
        Fail 'Executavel do Wallpaper Engine em G: nao existe; nao removi a origem.'
    }
    if (Test-Path -LiteralPath $oldEngineExe -PathType Leaf) {
        $oldEngineDir = Split-Path -Parent $oldEngineExe
        $desktop = [Environment]::GetFolderPath('Desktop')
        $oldFull = [System.IO.Path]::GetFullPath($oldEngineDir).TrimEnd('\')
        $desktopFull = [System.IO.Path]::GetFullPath($desktop).TrimEnd('\')
        if (-not $oldFull.StartsWith($desktopFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            Fail 'A origem do Wallpaper Engine nao esta no Desktop; nao a removi automaticamente.'
        }
        Get-Process wallpaper64,wallpaper32,wallpaper_engine -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $oldEngineDir -Recurse -Force
        Write-Host "Wallpaper Engine standalone antigo removido: $oldEngineDir" -ForegroundColor Green
    }
}

if ($RemoveOldCore -and (Test-Path -LiteralPath $OldCore -PathType Container)) {
    $oldFull = [System.IO.Path]::GetFullPath($OldCore).TrimEnd('\')
    $newFull = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
    if ($oldFull -ieq $newFull) { Fail 'Origem e destino sao iguais; abortado.' }

    # Logs/state have already been copied to G: by migrate_to_g.ps1. Never remove
    # the old tree unless the destination has the corresponding persistent dirs.
    foreach ($name in @('memory','logs','voice_profiles')) {
        if ((Test-Path -LiteralPath (Join-Path $OldCore $name)) -and -not (Test-Path -LiteralPath (Join-Path $Destination $name))) {
            Fail "Destino nao tem $name; nao removi C:\JARVIS."
        }
    }
    Remove-Item -LiteralPath $OldCore -Recurse -Force
    Write-Host "Core antigo removido de C:: $OldCore" -ForegroundColor Green
}

Write-Host ''
Write-Host 'Migracao G: validada.' -ForegroundColor Green
if (-not $RemoveOldCore -or -not $RemoveOldWallpaper -or -not $RemoveOldWallpaperEngine) {
    Write-Host 'Nada foi apagado sem switch explicito. Para limpeza final usa -RemoveOldCore, -RemoveOldWallpaper e/ou -RemoveOldWallpaperEngine.' -ForegroundColor Yellow
}
