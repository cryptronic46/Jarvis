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

if ($oldArgs -match '(?i)C:\\JARVIS') {
    $Shortcut.Arguments = $oldArgs.Replace('C:\JARVIS-Wallpaper','G:\JARVIS-Wallpaper').Replace('C:\JARVIS',$CorePath)
    $changed = $true
}
if ($oldTarget -match '(?i)^C:\\JARVIS') {
    $Shortcut.TargetPath = $oldTarget -replace '(?i)^C:\\JARVIS', $CorePath
    $changed = $true
}

if ($changed) {
    $Shortcut.WorkingDirectory = $CorePath
    $Shortcut.Save()
    Write-Host "Startup JARVIS corrigido para $CorePath" -ForegroundColor Green
} else {
    Write-Host 'Startup JARVIS: atalho existente não contém referência C:\JARVIS; sem alterações.' -ForegroundColor DarkGray
}
