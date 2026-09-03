$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try {
    [Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch { }

$Failures = [System.Collections.Generic.List[string]]::new()
Write-Host "=== JARVIS 0.27.8 REAL-MACHINE ACCEPTANCE ===" -ForegroundColor Cyan

# 1. Full validator: same Voice v2 config/classes as runtime.
& .\full_system_validation.ps1 -Destination $PSScriptRoot
if ($LASTEXITCODE -ne 0) { $Failures.Add("full_system_validation") }

# 2. Real /quit path followed by all JARVIS local-executor residency gates.
Write-Host "[ACCEPT] /quit -> local Qwen executor released" -ForegroundColor Cyan
@("/quit") | & .\run.ps1
if ($LASTEXITCODE -ne 0) { $Failures.Add("run_quit_cleanup") }
$StatePath = Join-Path $PSScriptRoot "memory\native_llama_runtime.json"
if (Test-Path -LiteralPath $StatePath) {
    try {
        $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        $PidValue = [int]$State.pid
        if ($PidValue -gt 0 -and $null -ne (Get-Process -Id $PidValue -ErrorAction SilentlyContinue)) {
            $Failures.Add("native_llama_still_resident:$PidValue")
        }
    } catch { $Failures.Add("native_llama_state_invalid") }
}
$RuntimeRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "runtime\llama.cpp"))
Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $PathValue = [System.IO.Path]::GetFullPath([string]$_.Path)
        if ($PathValue.StartsWith($RuntimeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            $Failures.Add("native_llama_orphan_process:$($_.Id)")
        }
    } catch { }
}

# If the Windows policy forced the loopback compatibility executor, the Ollama
# service may remain running, but JARVIS's Qwen model must no longer be resident.
try {
    $cfg = Get-Content -LiteralPath (Join-Path $PSScriptRoot "settings.json") -Raw | ConvertFrom-Json
    $OllamaHost = if ($cfg.ollama_host) { ([string]$cfg.ollama_host).TrimEnd('/') } else { "http://127.0.0.1:11434" }
    $ConfiguredModel = if ($cfg.model) { [string]$cfg.model } else { "qwen3:8b" }
    $ps = Invoke-RestMethod -UseBasicParsing -Uri ($OllamaHost + "/api/ps") -Method Get -TimeoutSec 3
    foreach ($row in @($ps.models)) {
        $name = if ($row.model) { [string]$row.model } elseif ($row.name) { [string]$row.name } else { "" }
        if ($name -eq $ConfiguredModel) { $Failures.Add("ollama_compat_model_still_resident:$name") }
    }
} catch { }

# 3. UTF-8 roundtrip through the installed Python.
# Build the pt-PT probe from Unicode code points so this script remains
# parse-safe even on Windows PowerShell 5.1 before encoding is validated.
$Utf8Probe = -join @(
    [char]0x00E3, ' ', [char]0x00E7, ' ', [char]0x00E1, ' ',
    [char]0x00E9, ' ', [char]0x00F3, ' ', [char]0x20AC, ' ',
    [char]0x2014, ' ', [char]0x201C, ' ', [char]0x201D
)
$RoundTrip = & .\.venv\Scripts\python.exe -c "import sys; print(sys.argv[1])" $Utf8Probe
if (($RoundTrip | Out-String).Trim() -ne $Utf8Probe) { $Failures.Add("utf8_pt_pt_roundtrip") }

if ($Failures.Count -gt 0) {
    Write-Host "RELEASE STATUS: BLOCKED" -ForegroundColor Red
    $Failures | ForEach-Object { Write-Host "FAIL: $_" -ForegroundColor Red }
    exit 1
}
Write-Host "RELEASE STATUS: REAL-MACHINE GATES PASSED" -ForegroundColor Green
exit 0
