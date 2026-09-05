param([string]$CorePath = "G:\JARVIS")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $Root "start_bridge.ps1"
$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "JARVIS Live Wallpaper Bridge.lnk"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StartScript`" -CorePath `"$CorePath`""
$Shortcut.WorkingDirectory = $Root
$Shortcut.IconLocation = "shell32.dll,13"
$Shortcut.Save()

Write-Host "Arranque automático instalado:" -ForegroundColor Green
Write-Host $ShortcutPath
Write-Host "O bridge continuará limitado a 127.0.0.1."
