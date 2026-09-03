param([int]$Port = 8765)

$ErrorActionPreference = "SilentlyContinue"
$Connections = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen
if (-not $Connections) {
    Write-Host "Não existe bridge a escutar na porta $Port."
    exit 0
}

$Pids = @($Connections | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($PidValue in $Pids) {
    $Process = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
    if ($Process -and $Process.ProcessName -like "python*") {
        Stop-Process -Id $PidValue -Force
        Write-Host "Bridge terminado (PID $PidValue)." -ForegroundColor Green
    } else {
        Write-Host "A porta $Port pertence a outro processo. Não foi terminado." -ForegroundColor Yellow
    }
}
