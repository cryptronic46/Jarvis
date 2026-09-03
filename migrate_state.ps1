param(
    [Parameter(Mandatory=$true)]
    [string]$Source
)

$ErrorActionPreference = "Stop"
$sourcePath = (Resolve-Path $Source).Path
$targetPath = (Get-Location).Path

Write-Host "A migrar estado de:"
Write-Host "  $sourcePath"
Write-Host "para:"
Write-Host "  $targetPath"

$items = @(
    "voice_profiles",
    "models\voiceid",
    ".cache\tts"
)

foreach ($item in $items) {
    $from = Join-Path $sourcePath $item
    $to = Join-Path $targetPath $item

    if (Test-Path $from) {
        $parent = Split-Path $to -Parent
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        if (Test-Path $to) {
            Remove-Item $to -Recurse -Force
        }
        Copy-Item $from $to -Recurse -Force
        Write-Host "OK: $item" -ForegroundColor Green
    }
}

Write-Host "Migração concluída. Não foram copiadas API keys; ficam no Credential Manager."
