$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "JARVIS Live Wallpaper Bridge.lnk"
if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
    Write-Host "Arranque automático removido." -ForegroundColor Green
} else {
    Write-Host "O arranque automático não estava instalado."
}
