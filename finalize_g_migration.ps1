param(
    [string]$OldCore = "C:\JARVIS",
    [string]$Destination = "G:\JARVIS",
    [switch]$RemoveOldCore
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Fail([string]$Message) {
    Write-Host "ERRO: $Message" -ForegroundColor Red
    exit 1
}

if (
    [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') -ine
    [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
) {
    Fail "Executa este script a partir de $Destination."
}

$PythonPath = Join-Path $Destination '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    Fail 'A nova .venv em G: ainda nao existe.'
}

if (-not (Test-Path -LiteralPath '.\memory\migration_g.json' -PathType Leaf)) {
    Fail 'Nao encontrei memory\migration_g.json.'
}

Write-Host 'A validar release em G:...' -ForegroundColor Cyan

& '.\verify_release.ps1' -Destination $Destination

if ($LASTEXITCODE -ne 0) {
    Fail 'verify_release.ps1 falhou.'
}

Write-Host 'A validar schema/configuracao...' -ForegroundColor Cyan

& $PythonPath -c "from jarvis_core.core.config import Settings; r=Settings.ensure_file_schema(); Settings.load(); print(r)"

if ($LASTEXITCODE -ne 0) {
    Fail 'Schema/configuracao nao passou validacao.'
}

if ($RemoveOldCore -and (Test-Path -LiteralPath $OldCore -PathType Container)) {
    $oldFull = [System.IO.Path]::GetFullPath($OldCore).TrimEnd('\')
    $newFull = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')

    if ($oldFull -ieq $newFull) {
        Fail 'Origem e destino sao iguais; operacao cancelada.'
    }

    foreach ($name in @(
        'memory',
        'knowledge',
        'logs',
        'models',
        '.cache',
        'skills'
    )) {
        if (
            (Test-Path -LiteralPath (Join-Path $OldCore $name)) -and
            -not (Test-Path -LiteralPath (Join-Path $Destination $name))
        ) {
            Fail "Destino nao tem $name; nao removi C:\JARVIS."
        }
    }

    foreach ($name in @(
        'settings.json',
        'apps.json'
    )) {
        if (
            (Test-Path -LiteralPath (Join-Path $OldCore $name) -PathType Leaf) -and
            -not (Test-Path -LiteralPath (Join-Path $Destination $name) -PathType Leaf)
        ) {
            Fail "Destino nao tem $name; nao removi C:\JARVIS."
        }
    }

    Remove-Item -LiteralPath $OldCore -Recurse -Force
    Write-Host "Core antigo removido de C:: $OldCore" -ForegroundColor Green
}

Write-Host ""
Write-Host 'Migracao G: validada.' -ForegroundColor Green

if (-not $RemoveOldCore) {
    Write-Host 'Nada foi apagado sem -RemoveOldCore explicito.' -ForegroundColor Yellow
}
