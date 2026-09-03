param(
    [switch]$SkipRuntimeDownload,
    [switch]$SkipModelDownload,
    [switch]$RepairRuntime,
    [switch]$PrepareTrustedCudaRuntime
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$RuntimeDir = Join-Path $PSScriptRoot "runtime\llama.cpp"
$ModelDir = Join-Path $PSScriptRoot "models\llm"
$ServerPath = Join-Path $RuntimeDir "llama-server.exe"
$ProvenancePath = Join-Path $RuntimeDir "jarvis_runtime_provenance.json"
$LlamaCppTag = "b10516"
$LlamaMainSha256 = "96d64faeb5b8e655341f32b26ad3e51fbea8bff0bc8120ad3dbffdc0b05b8ad3"
$LlamaCudaSha256 = "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"
$LlamaVulkanSha256 = "530f57d2a874ce017827c1e5a926812b9d5de4667248575d1372b1c0acf94d83"
$QwenQ4Sha256 = "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"
$ModelPath = Join-Path $ModelDir "qwen3-8b.gguf"
New-Item -ItemType Directory -Force -Path $RuntimeDir, $ModelDir | Out-Null

function Test-Gguf([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $bytes = New-Object byte[] 4
        if ($stream.Read($bytes, 0, 4) -ne 4) { return $false }
        return ([System.Text.Encoding]::ASCII.GetString($bytes) -eq "GGUF")
    }
    finally { $stream.Dispose() }
}

function Assert-Sha256([string]$Path, [string]$Expected) {
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $Path. Expected $Expected, got $Actual"
    }
}

function Format-ExitCode([int]$Code) {
    $bytes = [System.BitConverter]::GetBytes([int]$Code)
    $unsigned = [System.BitConverter]::ToUInt32($bytes, 0)
    return ('0x{0:X8}' -f $unsigned)
}

function Get-MotwFiles([string]$Root) {
    $found = @()
    if (-not (Test-Path -LiteralPath $Root)) { return $found }
    foreach ($file in @(Get-ChildItem -LiteralPath $Root -File -Recurse -ErrorAction SilentlyContinue)) {
        $ads = $file.FullName + ':Zone.Identifier'
        try {
            if (Test-Path -LiteralPath $ads -ErrorAction SilentlyContinue) { $found += $file.FullName }
        }
        catch { }
    }
    return $found
}

function Invoke-NativeRuntimeProbe {
    if (-not (Test-Path -LiteralPath $ServerPath -PathType Leaf)) {
        return [pscustomobject]@{ ok=$false; exit_code=$null; exit_hex='MISSING'; output='llama-server.exe missing' }
    }
    $stdout = Join-Path $env:TEMP ("jarvis_llama_probe_out_" + [guid]::NewGuid().ToString('N') + '.txt')
    $stderr = Join-Path $env:TEMP ("jarvis_llama_probe_err_" + [guid]::NewGuid().ToString('N') + '.txt')
    try {
        try {
            $p = Start-Process -FilePath $ServerPath -ArgumentList @('--version') -WorkingDirectory $RuntimeDir -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
            $code = [int]$p.ExitCode
            $text = ''
            if (Test-Path -LiteralPath $stdout) { $text += (Get-Content -LiteralPath $stdout -Raw -ErrorAction SilentlyContinue) }
            if (Test-Path -LiteralPath $stderr) { $text += (Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue) }
            return [pscustomobject]@{ ok=($code -eq 0); exit_code=$code; exit_hex=(Format-ExitCode $code); output=$text.Trim() }
        }
        catch {
            return [pscustomobject]@{ ok=$false; exit_code=$null; exit_hex='START_ERROR'; output=$_.Exception.Message }
        }
    }
    finally {
        Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
    }
}

function Copy-MainRuntimeFromStage([string]$Stage) {
    $server = Get-ChildItem -LiteralPath $Stage -Recurse -Filter 'llama-server.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $server) { throw 'Verified llama.cpp archive did not contain llama-server.exe.' }
    $sourceDir = $server.Directory.FullName
    Get-ChildItem -LiteralPath $sourceDir -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $RuntimeDir -Recurse -Force
    }
}

function Copy-CudaRuntimeFromStage([string]$Stage) {
    $dlls = @(Get-ChildItem -LiteralPath $Stage -Recurse -Filter '*.dll' -File -ErrorAction SilentlyContinue)
    if ($dlls.Count -eq 0) { throw 'Verified CUDA runtime archive did not contain DLLs.' }
    foreach ($dll in $dlls) {
        Copy-Item -LiteralPath $dll.FullName -Destination (Join-Path $RuntimeDir $dll.Name) -Force
    }
}

function Install-PinnedNativeRuntime([string]$Variant = "cuda12") {
    if ($SkipRuntimeDownload) { throw "llama.cpp runtime repair/download was disabled with -SkipRuntimeDownload." }
    $Variant = $Variant.ToLowerInvariant()
    if ($Variant -notin @('cuda12','vulkan')) { throw "Unsupported native runtime variant: $Variant" }
    Write-Host ("[JARVIS/NATIVE] Installing verified llama.cpp runtime " + $LlamaCppTag + " / " + $Variant + "...") -ForegroundColor Cyan
    $release = Invoke-RestMethod -Headers @{"User-Agent"="JARVIS-0.27.8"} -Uri ("https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/" + $LlamaCppTag)
    if ($Variant -eq 'cuda12') {
        $main = @($release.assets) | Where-Object { $_.name -match '^llama-.*-bin-win-cuda-12\.4-x64\.zip$' } | Select-Object -First 1
        $cuda = @($release.assets) | Where-Object { $_.name -eq 'cudart-llama-bin-win-cuda-12.4-x64.zip' } | Select-Object -First 1
        $mainSha = $LlamaMainSha256
        if ($null -eq $main) { throw "Official llama.cpp Windows CUDA 12.4 asset not found." }
        if ($null -eq $cuda) { throw "Official llama.cpp CUDA 12.4 DLL asset not found." }
    }
    else {
        $main = @($release.assets) | Where-Object { $_.name -eq ("llama-" + $LlamaCppTag + "-bin-win-vulkan-x64.zip") } | Select-Object -First 1
        $cuda = $null
        $mainSha = $LlamaVulkanSha256
        if ($null -eq $main) { throw "Official llama.cpp Windows Vulkan x64 asset not found." }
    }

    $temp = Join-Path $env:TEMP ("jarvis_llamacpp_" + [guid]::NewGuid().ToString('N'))
    $mainStage = Join-Path $temp 'main'
    $cudaStage = Join-Path $temp 'cuda'
    New-Item -ItemType Directory -Force -Path $temp,$mainStage,$cudaStage | Out-Null
    try {
        $mainZip = Join-Path $temp "llama.zip"
        Invoke-WebRequest -UseBasicParsing -Headers @{"User-Agent"="JARVIS-0.27.8"} -Uri $main.browser_download_url -OutFile $mainZip
        if ($Variant -eq 'cuda12') { Assert-Sha256 $mainZip $LlamaMainSha256 } else { Assert-Sha256 $mainZip $LlamaVulkanSha256 }
        Unblock-File -LiteralPath $mainZip -ErrorAction Stop
        if ($Variant -eq 'cuda12') { Assert-Sha256 $mainZip $LlamaMainSha256 } else { Assert-Sha256 $mainZip $LlamaVulkanSha256 }
        Expand-Archive -LiteralPath $mainZip -DestinationPath $mainStage -Force

        if ($Variant -eq 'cuda12') {
            $cudaZip = Join-Path $temp "cudart.zip"
            Invoke-WebRequest -UseBasicParsing -Headers @{"User-Agent"="JARVIS-0.27.8"} -Uri $cuda.browser_download_url -OutFile $cudaZip
            Assert-Sha256 $cudaZip $LlamaCudaSha256
            Unblock-File -LiteralPath $cudaZip -ErrorAction Stop
            Assert-Sha256 $cudaZip $LlamaCudaSha256
            Expand-Archive -LiteralPath $cudaZip -DestinationPath $cudaStage -Force
        }

        Get-ChildItem -LiteralPath $RuntimeDir -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction Stop
        Copy-MainRuntimeFromStage $mainStage
        if ($Variant -eq 'cuda12') { Copy-CudaRuntimeFromStage $cudaStage }

        foreach ($file in @(Get-ChildItem -LiteralPath $RuntimeDir -File -Recurse -ErrorAction Stop)) {
            Unblock-File -LiteralPath $file.FullName -ErrorAction Stop
        }

        $runtimeHashes = @()
        foreach ($runtimeFile in @(Get-ChildItem -LiteralPath $RuntimeDir -File -Recurse -ErrorAction Stop | Where-Object { $_.Extension -in @('.exe','.dll') } | Sort-Object FullName)) {
            $runtimeHashes += [ordered]@{
                path = $runtimeFile.FullName.Substring($RuntimeDir.Length).TrimStart('\').Replace('\','/')
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $runtimeFile.FullName).Hash.ToLowerInvariant()
                size = [int64]$runtimeFile.Length
            }
        }
        $prov = [ordered]@{
            installed_by = 'JARVIS'
            release = '0.27.8'
            llama_cpp_tag = $LlamaCppTag
            variant = $Variant
            main_archive_sha256 = $mainSha
            cuda_archive_sha256 = $(if ($Variant -eq 'cuda12') { $LlamaCudaSha256 } else { $null })
            security = 'sha256_verified_then_unblocked'
            runtime_file_hashes = $runtimeHashes
            installed_at = (Get-Date).ToString('o')
        }
        ($prov | ConvertTo-Json -Depth 4) | Set-Content -LiteralPath $ProvenancePath -Encoding UTF8
    }
    finally { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
}

function Test-OllamaCompatExecutor {
    $base = 'http://127.0.0.1:11434'
    $model = 'qwen3:8b'
    function Probe-Tags {
        try {
            $r = Invoke-RestMethod -UseBasicParsing -Uri ($base + '/api/tags') -Method Get -TimeoutSec 3
            $names = @($r.models | ForEach-Object { if ($_.model) { [string]$_.model } elseif ($_.name) { [string]$_.name } })
            return [pscustomobject]@{ online=$true; model_ok=($names -contains $model); models=$names; error=$null }
        }
        catch { return [pscustomobject]@{ online=$false; model_ok=$false; models=@(); error=$_.Exception.Message } }
    }
    $probe = Probe-Tags
    if (-not $probe.online) {
        $cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            try { Start-Process -FilePath $cmd.Source -ArgumentList @('serve') -WindowStyle Hidden | Out-Null } catch { }
            $deadline = (Get-Date).AddSeconds(10)
            do {
                Start-Sleep -Milliseconds 500
                $probe = Probe-Tags
                if ($probe.online) { break }
            } while ((Get-Date) -lt $deadline)
        }
    }
    return [pscustomobject]@{ ok=($probe.online -and $probe.model_ok); online=$probe.online; model_ok=$probe.model_ok; models=$probe.models; error=$probe.error }
}

function Find-OllamaQwenBlob {
    $Root = Join-Path $env:USERPROFILE ".ollama\models"
    $Manifest = Join-Path $Root "manifests\registry.ollama.ai\library\qwen3\8b"
    if (-not (Test-Path -LiteralPath $Manifest)) { return $null }
    try { $data = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json } catch { return $null }
    foreach ($layer in @($data.layers)) {
        $media = [string]$layer.mediaType
        $digest = [string]$layer.digest
        if ($media -notmatch "model" -or $digest -notmatch '^sha256:') { continue }
        $Blob = Join-Path $Root ("blobs\sha256-" + $digest.Substring(7))
        if (Test-Gguf $Blob) { return $Blob }
    }
    return $null
}

if ($PrepareTrustedCudaRuntime) {
    if ($SkipRuntimeDownload) { throw '-PrepareTrustedCudaRuntime cannot be combined with -SkipRuntimeDownload.' }
    Write-Host '[JARVIS/TRUST] Preparing a fresh SHA-256-verified CUDA runtime without probing it yet...' -ForegroundColor Cyan
    Install-PinnedNativeRuntime 'cuda12'
    Write-Host '[JARVIS/TRUST] CUDA runtime prepared and per-file SHA-256 inventory recorded.' -ForegroundColor Green
    Write-Host '[JARVIS/TRUST] Next: .\setup_appcontrol_trust.ps1 -Mode Plan' -ForegroundColor Cyan
    exit 0
}

$probe = Invoke-NativeRuntimeProbe
$UsingOllamaCompat = $false
$NativeVariant = 'existing'
if ($RepairRuntime -or -not $probe.ok) {
    if (Test-Path -LiteralPath $ServerPath) {
        Write-Warning ("Existing native runtime probe failed: " + $probe.exit_hex + " " + $probe.output)
        if ($probe.exit_hex -eq '0xC0E90002') { Write-Warning "Windows returned 0xC0E90002 (Bad Image / Code Integrity)." }
        $motw = @(Get-MotwFiles $RuntimeDir)
        if ($motw.Count -gt 0) { Write-Warning ("Detected Mark-of-the-Web on " + $motw.Count + " native runtime file(s).") }
    }

    Install-PinnedNativeRuntime 'cuda12'
    $NativeVariant = 'cuda12'
    $probe = Invoke-NativeRuntimeProbe

    if (-not $probe.ok) {
        Write-Warning ("Verified CUDA llama.cpp probe failed: " + $probe.exit_hex + ". Trying the official Vulkan x64 build before any compatibility fallback.")
        Install-PinnedNativeRuntime 'vulkan'
        $NativeVariant = 'vulkan'
        $probe = Invoke-NativeRuntimeProbe
    }
}

if (-not $probe.ok) {
    $motw = @(Get-MotwFiles $RuntimeDir)
    $extra = if ($motw.Count -gt 0) { " MOTW remains on $($motw.Count) runtime file(s)." } else { "" }
    $compat = Test-OllamaCompatExecutor
    if ($compat.ok) {
        $UsingOllamaCompat = $true
        Write-Warning ("Both verified standalone llama.cpp variants were rejected/unavailable (" + $probe.exit_hex + ").")
        Write-Host "[JARVIS/LOCAL] Existing Ollama + qwen3:8b detected. Enabling LOCAL compatibility executor only." -ForegroundColor Yellow
        Write-Host "[JARVIS/LOCAL] JARVIS remains the orchestration brain; external AI is HARD BLOCKED. Ollama only executes local Qwen tokens." -ForegroundColor DarkGray
    }
    else {
        if ($probe.exit_hex -eq '0xC0E90002') {
            throw "Verified CUDA and Vulkan llama.cpp builds are both blocked by Windows Code Integrity.$extra No healthy local Ollama qwen3:8b compatibility executor was found. Run .\diagnose_app_control.ps1 for evidence; JARVIS will not disable Windows security."
        }
        throw "llama-server.exe failed its startup probe ($($probe.exit_hex)).$extra No healthy local compatibility executor was found. Probe: $($probe.output)"
    }
}
else {
    Write-Host ("[JARVIS/NATIVE] Runtime probe OK (" + $NativeVariant + "): " + (($probe.output -split "`r?`n")[0])) -ForegroundColor Green
}

$DownloadedOfficialModel = $false
if (-not (Test-Gguf $ModelPath) -and -not $UsingOllamaCompat) {
    $legacyBlob = Find-OllamaQwenBlob
    if ($null -ne $legacyBlob) {
        Write-Host "[JARVIS/NATIVE] Migrating existing Qwen3 8B GGUF from Ollama cache..." -ForegroundColor Cyan
        Copy-Item -LiteralPath $legacyBlob -Destination $ModelPath -Force
    }
    elseif (-not $SkipModelDownload) {
        Write-Host "[JARVIS/NATIVE] Downloading official Qwen3-8B Q4_K_M GGUF..." -ForegroundColor Cyan
        $url = "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf?download=true"
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($null -ne $curl) {
            & $curl.Source -L --fail --retry 3 -o $ModelPath $url
            if ($LASTEXITCODE -ne 0) { throw "Qwen3 model download failed." }
        }
        else { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $ModelPath }
        $DownloadedOfficialModel = $true
    }
}
if ($DownloadedOfficialModel) { Assert-Sha256 $ModelPath $QwenQ4Sha256 }
if (-not (Test-Gguf $ModelPath) -and -not $UsingOllamaCompat) {
    if ($SkipModelDownload) {
        Write-Warning "Native GGUF model is not installed yet. Runtime/tests can proceed, but JARVIS reasoning requires a later .\setup_native_brain.ps1 run."
    }
    else { throw "Valid GGUF model missing: $ModelPath" }
}

# JARVIS App Control enforcement is disabled in this release. Keep the local
# compatibility executor available regardless of stale legacy trust-state.
$AllowCompat = $true
$AllowCompatPython = 'True'
& ".\.venv\Scripts\python.exe" -c "from jarvis_core.core.config import Settings; print(Settings.update_file_values({'local_llm_backend':'jarvis_local','local_llm_allow_ollama_compat':$AllowCompatPython,'native_llama_server_path':'runtime/llama.cpp/llama-server.exe','native_llama_model_path':'models/llm/qwen3-8b.gguf','external_ai_enabled':False,'cloud_enabled':False,'expert_escalation_enabled':False,'external_ai_auto_escalate_complex':False}))"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($UsingOllamaCompat) {
    Write-Host "[JARVIS/LOCAL] Brain ready with local compatibility executor (Ollama/qwen3:8b). External AI is HARD BLOCKED." -ForegroundColor Green
}
elseif (Test-Gguf $ModelPath) {
    Write-Host "[JARVIS/NATIVE] Native brain ready. Standalone llama.cpp is the active local executor." -ForegroundColor Green
}
else {
    Write-Host "[JARVIS/NATIVE] Native runtime ready; model installation deferred." -ForegroundColor Yellow
}
