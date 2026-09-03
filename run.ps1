$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try {
    [Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch { }
if (-not (Test-Path ".venv\Scripts\python.exe")) { Write-Host "Executa primeiro: .\setup.ps1"; exit 1 }

function Stop-JarvisNativeBrain {
    $state = Join-Path $PSScriptRoot "memory\native_llama_runtime.json"
    $runtimeRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "runtime\llama.cpp"))
    $pids = [System.Collections.Generic.HashSet[int]]::new()

    if (Test-Path -LiteralPath $state) {
        try {
            $data = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
            $pidValue = [int]$data.pid
            if ($pidValue -gt 0) { [void]$pids.Add($pidValue) }
        } catch { return $false }
    }

    # Catch a JARVIS-owned orphan even if the state file was lost. Never kill a
    # llama-server outside this installation's runtime directory.
    Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $path = [System.IO.Path]::GetFullPath([string]$_.Path)
            if ($path.StartsWith($runtimeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                [void]$pids.Add([int]$_.Id)
            }
        } catch { }
    }

    foreach ($pidValue in @($pids)) {
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    }
    if ($pids.Count -gt 0) { Start-Sleep -Milliseconds 600 }

    $alive = @()
    foreach ($pidValue in @($pids)) {
        if ($null -ne (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) { $alive += $pidValue }
    }
    if ($alive.Count -eq 0) {
        Remove-Item $state -Force -ErrorAction SilentlyContinue
        if ($pids.Count -gt 0) {
            Write-Host "[JARVIS/VRAM] native llama.cpp runtime stopped." -ForegroundColor DarkGreen
        }
        return $true
    }
    Write-Warning ("JARVIS shutdown gate: native llama.cpp PID(s) still running: " + ($alive -join ", "))
    return $false
}



function Stop-JarvisOllamaCompatModel {
    # Only unload Ollama when this JARVIS process selected it as compatibility
    # executor. This avoids touching an unrelated Ollama session when native
    # llama.cpp was the active executor.
    $executorState = Join-Path $PSScriptRoot "memory\local_llm_executor.json"
    if (-not (Test-Path -LiteralPath $executorState)) { return $true }
    try {
        $state = Get-Content -LiteralPath $executorState -Raw | ConvertFrom-Json
        if ([string]$state.selected -ne "ollama_local_compat") { Remove-Item $executorState -Force -ErrorAction SilentlyContinue; return $true }
    } catch { return $true }
    try {
        $settingsPath = Join-Path $PSScriptRoot "settings.json"
        $model = "qwen3:8b"
        $host = "http://127.0.0.1:11434"
        if (Test-Path -LiteralPath $settingsPath) {
            try {
                $cfg = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
                if ($cfg.model) { $model = [string]$cfg.model }
                if ($cfg.ollama_host) { $host = ([string]$cfg.ollama_host).TrimEnd('/') }
            } catch { }
        }
        $body = @{ model=$model; prompt=""; stream=$false; keep_alive=0 } | ConvertTo-Json -Compress
        Invoke-RestMethod -UseBasicParsing -Uri ($host + "/api/generate") -Method Post -ContentType "application/json" -Body $body -TimeoutSec 8 | Out-Null
        Remove-Item $executorState -Force -ErrorAction SilentlyContinue
        Write-Host "[JARVIS/VRAM] local compatibility model release requested." -ForegroundColor DarkGreen
        return $true
    }
    catch {
        # Offline/not-installed Ollama is normal when native llama.cpp is active.
        return $true
    }
}

$JarvisExitCode = 0
$CleanupOk = $true
try {
    & ".\.venv\Scripts\python.exe" jarvis.py
    $JarvisExitCode = $LASTEXITCODE
}
finally {
    $CleanupOk = Stop-JarvisNativeBrain
    [void](Stop-JarvisOllamaCompatModel)
}
if (-not $CleanupOk) { exit 23 }
exit $JarvisExitCode
