$ErrorActionPreference = 'Stop'

$CorePath = $PSScriptRoot
$Startup = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $Startup 'JARVIS Desktop.lnk'

if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) {
    Write-Host 'Startup JARVIS: sem atalho existente; nada foi criado.' -ForegroundColor DarkGray
    exit 0
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$oldArgs = [string]$Shortcut.Arguments
$oldTarget = [string]$Shortcut.TargetPath
$changed = $false

$corePattern = '(?i)C:\\JARVIS(?![-A-Za-z0-9_])'
$coreStartPattern = '(?i)^C:\\JARVIS(?![-A-Za-z0-9_])'

if ($oldArgs -match $corePattern) {
    $Shortcut.Arguments = $oldArgs -replace $corePattern, $CorePath
    $changed = $true
}

if ($oldTarget -match $coreStartPattern) {
    $Shortcut.TargetPath = $oldTarget -replace $coreStartPattern, $CorePath
    $changed = $true
}

if ($changed) {
    $Shortcut.WorkingDirectory = $CorePath
    $Shortcut.Save()
    Write-Host "Startup JARVIS corrigido para $CorePath" -ForegroundColor Green
}
else {
    Write-Host 'Startup JARVIS: atalho existente nao contem referencia ao Core antigo; sem alteracoes.' -ForegroundColor DarkGray
}
