$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $Root "data"
$Source = Join-Path $DataDir "sessions.dpapi"

if (-not (Test-Path $Source)) {
    throw "Encrypted history not found: $Source"
}

$BackupDir = Join-Path $DataDir "backups"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Destination = Join-Path $BackupDir "sessions-$Stamp.dpapi"
Copy-Item -LiteralPath $Source -Destination $Destination -ErrorAction Stop

$SourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Source).Hash
$BackupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash

if ($SourceHash -ne $BackupHash) {
    Remove-Item -LiteralPath $Destination -ErrorAction SilentlyContinue
    throw "Backup verification failed: SHA256 mismatch"
}

Write-Host "[PASS] Encrypted history backup created and SHA256 verified:"
Write-Host "       $Destination"
