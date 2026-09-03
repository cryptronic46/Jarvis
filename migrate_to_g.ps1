param(
    [string]$Source = "C:\JARVIS",
    [string]$Destination = "G:\JARVIS",
    [string]$WallpaperDestination = "G:\JARVIS-Wallpaper",
    [string]$StandaloneWallpaperEngineDestination = "G:\WallpaperEngine"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Fail([string]$Message) {
    Write-Host "ERRO: $Message" -ForegroundColor Red
    exit 1
}

function Copy-TreeSafe([string]$From, [string]$To, [string]$Label) {
    if (-not (Test-Path -LiteralPath $From)) { return $false }
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    $null = & robocopy.exe $From $To /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /XJ /NP /NFL /NDL
    $code = $LASTEXITCODE
    if ($code -ge 8) { Fail "$Label falhou no robocopy (exit code $code)." }
    return $true
}

function Copy-FileSafe([string]$From, [string]$To) {
    if (-not (Test-Path -LiteralPath $From -PathType Leaf)) { return }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $To) | Out-Null
    Copy-Item -LiteralPath $From -Destination $To -Force
}

function Get-WallpaperProcessPath {
    $proc = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @('wallpaper64.exe','wallpaper32.exe','wallpaper_engine.exe') } |
        Select-Object -First 1
    if ($proc -and $proc.ExecutablePath) { return [string]$proc.ExecutablePath }

    # It may be closed during migration. Search only the OWNER Desktop for a
    # standalone copy; Steam libraries are handled separately and are never
    # moved behind Steam's back.
    $desktop = [Environment]::GetFolderPath('Desktop')
    if (Test-Path -LiteralPath $desktop -PathType Container) {
        foreach ($exeName in @('wallpaper64.exe','wallpaper32.exe','wallpaper_engine.exe')) {
            $found = Get-ChildItem -LiteralPath $desktop -File -Filter $exeName -Recurse -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($found) { return [string]$found.FullName }
        }
    }
    return $null
}

Write-Host ""; Write-Host "=== JARVIS 0.26.3 - MIGRACAO PARA G: ===" -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath "G:\")) { Fail "A unidade G: nao esta disponivel." }
if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
    Fail "Extrai primeiro a release corrigida para $Destination e volta a executar este script a partir de G:."
}

$running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -like 'python*' -and $_.CommandLine -match '(?i)jarvis\.py'
})
if ($running.Count -gt 0) { Fail "Fecha o JARVIS com /quit antes da migracao." }

$report = [ordered]@{
    version = '0.26.3'
    started_at = (Get-Date).ToString('o')
    source = $Source
    destination = $Destination
    persistent_copied = @()
    wallpaper_source = $null
    wallpaper_destination = $WallpaperDestination
    wallpaper_engine_source = $null
    wallpaper_engine_destination = $null
    old_venv_copied = $false
    notes = @()
}

# Never move/copy the old venv. Windows venv launchers may retain absolute paths.
$report.notes += 'Old .venv intentionally not copied; setup.ps1 recreates it on G:.'

if (Test-Path -LiteralPath $Source -PathType Container) {
    foreach ($name in @('memory','knowledge','logs','voice_profiles','models','.cache','skills')) {
        $from = Join-Path $Source $name
        $to = Join-Path $Destination $name
        if (Copy-TreeSafe $from $to "Migracao de $name") { $report.persistent_copied += $name }
    }
    foreach ($name in @('settings.json','apps.json')) {
        $from = Join-Path $Source $name
        if (Test-Path -LiteralPath $from -PathType Leaf) {
            Copy-FileSafe $from (Join-Path $Destination $name)
            $report.persistent_copied += $name
        }
    }
}
else {
    $report.notes += "Source core not found: $Source. Using state already present in release package."
}

# Find the JARVIS live-wallpaper add-on. Prefer the canonical old path, then Desktop.
$desktop = [Environment]::GetFolderPath('Desktop')
$wallpaperCandidates = @(
    (Join-Path (Split-Path -Parent $Source) 'JARVIS-Wallpaper'),
    (Join-Path $desktop 'JARVIS-Wallpaper')
)
if (Test-Path -LiteralPath $desktop) {
    $wallpaperCandidates += @(Get-ChildItem -LiteralPath $desktop -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'JARVIS_Live_Wallpaper*' -or $_.Name -like 'JARVIS-Wallpaper*' } |
        ForEach-Object { $_.FullName })
}
$wallpaperSource = $wallpaperCandidates | Where-Object {
    $_ -and (Test-Path -LiteralPath $_ -PathType Container) -and ([System.IO.Path]::GetFullPath($_).TrimEnd('\') -ine [System.IO.Path]::GetFullPath($WallpaperDestination).TrimEnd('\'))
} | Select-Object -First 1
if ($wallpaperSource) {
    if (Copy-TreeSafe $wallpaperSource $WallpaperDestination 'Migracao do add-on Wallpaper') {
        $report.wallpaper_source = $wallpaperSource
        $report.notes += 'Wallpaper add-on copied to G:. Old copy retained until finalize_g_migration.ps1.'
    }
}
elseif (Test-Path -LiteralPath $WallpaperDestination -PathType Container) {
    $report.notes += 'Wallpaper add-on already present on G:.'
}
else {
    $report.notes += 'Wallpaper add-on source not found automatically.'
}

# If Wallpaper Engine itself is a standalone folder on Desktop, copy it to G:.
# Steam-managed installs are intentionally NOT moved behind Steam's back.
$enginePath = Get-WallpaperProcessPath
if ($enginePath) {
    $report.wallpaper_engine_source = $enginePath
    $engineDir = Split-Path -Parent $enginePath
    $engineLower = $engineDir.ToLowerInvariant()
    $desktopLower = $desktop.ToLowerInvariant()
    if ($engineLower.StartsWith($desktopLower)) {
        Get-Process wallpaper64,wallpaper32,wallpaper_engine -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        if (Copy-TreeSafe $engineDir $StandaloneWallpaperEngineDestination 'Migracao do Wallpaper Engine standalone') {
            $newExe = Join-Path $StandaloneWallpaperEngineDestination (Split-Path -Leaf $enginePath)
            $report.wallpaper_engine_destination = $newExe
            $report.notes += 'Standalone Wallpaper Engine copied from Desktop to G:. Old copy retained until finalization.'
        }
    }
    elseif ($engineLower -match '\\steamapps\\common\\wallpaper_engine') {
        $report.notes += 'Wallpaper Engine is Steam-managed. Move the Steam app/library to G: using Steam Storage; JARVIS 0.26.3 auto-detects Steam libraries on the same drive.'
    }
    else {
        $report.notes += 'Wallpaper Engine is not on Desktop. JARVIS will prefer a G: installation when one exists.'
    }
}

# Normalize active settings for G: without deleting historical logs.
$settingsPath = Join-Path $Destination 'settings.json'
if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    $settings.desktop_wallpaper_root = $WallpaperDestination
    if ($report.wallpaper_engine_destination) {
        $settings.desktop_wallpaper_engine_path = $report.wallpaper_engine_destination
    }
    $settings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $settingsPath -Encoding UTF8
}

$memoryDir = Join-Path $Destination 'memory'
New-Item -ItemType Directory -Force -Path $memoryDir | Out-Null
$report.completed_at = (Get-Date).ToString('o')
$reportPath = Join-Path $memoryDir 'migration_g.json'
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host ""; Write-Host "Dados persistentes migrados para G:." -ForegroundColor Green
Write-Host "Relatorio: $reportPath"
Write-Host "A .venv antiga NAO foi copiada. Agora executa em G:\JARVIS:" -ForegroundColor Yellow
Write-Host "  .\setup.ps1 -SkipModel"
Write-Host "  .\setup_voice_v2.ps1"
Write-Host "  .\run.ps1"
Write-Host "Depois de validares Core + voz + wallpaper, executa .\finalize_g_migration.ps1 com os switches de limpeza que pretenderes; nada antigo e apagado sem pedido explicito." -ForegroundColor Yellow
