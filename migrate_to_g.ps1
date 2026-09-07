param(
    [string]$Source = "C:\JARVIS",
    [string]$Destination = "G:\JARVIS"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Fail([string]$Message) {
    Write-Host "ERRO: $Message" -ForegroundColor Red
    exit 1
}

function Copy-TreeSafe([string]$From, [string]$To, [string]$Label) {
    if (-not (Test-Path -LiteralPath $From)) {
        return $false
    }

    New-Item -ItemType Directory -Force -Path $To | Out-Null

    $null = & robocopy.exe $From $To /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /XJ /NP /NFL /NDL
    $code = $LASTEXITCODE

    if ($code -ge 8) {
        Fail "$Label falhou no robocopy (exit code $code)."
    }

    return $true
}

function Copy-FileSafe([string]$From, [string]$To) {
    if (-not (Test-Path -LiteralPath $From -PathType Leaf)) {
        return
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $To) | Out-Null
    Copy-Item -LiteralPath $From -Destination $To -Force
}

Write-Host ""
Write-Host "=== JARVIS 0.27.8 - MIGRACAO DO CORE PARA G: ===" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath "G:")) {
    Fail "A unidade G: nao esta disponivel."
}

if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
    Fail "Extrai primeiro a release corrigida para $Destination e volta a executar este script a partir de G:."
}

$running = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -like 'python*' -and
        $_.CommandLine -match '(?i)jarvis.py'
    }
)

if ($running.Count -gt 0) {
    Fail "Fecha o JARVIS com /quit antes da migracao."
}

$report = [ordered]@{
    version = '0.27.8'
    started_at = (Get-Date).ToString('o')
    source = $Source
    destination = $Destination
    persistent_copied = @()
    old_venv_copied = $false
    notes = @()
}

$report.notes += 'Old .venv intentionally not copied; setup.ps1 recreates it on G:.'

if (Test-Path -LiteralPath $Source -PathType Container) {
    foreach ($name in @(
        'memory',
        'knowledge',
        'logs',
        'models',
        '.cache',
        'skills'
    )) {
        $from = Join-Path $Source $name
        $to = Join-Path $Destination $name

        if (Copy-TreeSafe $from $to "Migracao de $name") {
            $report.persistent_copied += $name
        }
    }

    foreach ($name in @(
        'settings.json',
        'apps.json'
    )) {
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

$memoryDir = Join-Path $Destination 'memory'
New-Item -ItemType Directory -Force -Path $memoryDir | Out-Null

$report.completed_at = (Get-Date).ToString('o')
$reportPath = Join-Path $memoryDir 'migration_g.json'

$report |
    ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host ""
Write-Host "Dados persistentes do Core migrados para G:." -ForegroundColor Green
Write-Host "Relatorio: $reportPath"
Write-Host "A .venv antiga NAO foi copiada. Agora executa em G:\JARVIS:" -ForegroundColor Yellow
Write-Host "  .\setup.ps1 -SkipModel"
Write-Host "  .\verify_release.ps1"
Write-Host "  .\run.ps1"
Write-Host "Depois de validares o Core, usa .\finalize_g_migration.ps1 -RemoveOldCore apenas se quiseres remover explicitamente C:\JARVIS." -ForegroundColor Yellow
