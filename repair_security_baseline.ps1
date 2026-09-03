param(
    [string]$Destination = "G:\JARVIS"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $Destination
$Python = ".\.venv\Scripts\python.exe"

function Fail([string]$Message) {
    Write-Host "ERRO: $Message" -ForegroundColor Red
    exit 1
}

# Windows native process exit codes are signed Int32 in PowerShell/.NET.
# Reinterpret the same 32 bits instead of casting a negative Int32 to UInt32,
# which throws in Windows PowerShell 5.1 (for example -1058471934 == 0xC0E90002).
function Format-WindowsExitCode([int]$Code) {
    $Bytes = [System.BitConverter]::GetBytes([int]$Code)
    $Unsigned = [System.BitConverter]::ToUInt32($Bytes, 0)
    return ('0x{0:X8}' -f $Unsigned)
}

if (-not (Test-Path -LiteralPath $Python)) {
    Fail "Ambiente virtual nao existe. Executa primeiro .\setup.ps1 -SkipModel."
}
if (-not (Test-Path -LiteralPath ".\release_manifest.json")) {
    Fail "release_manifest.json em falta."
}
$Manifest = Get-Content ".\release_manifest.json" -Raw | ConvertFrom-Json
$ReleaseVersion = [string]$Manifest.release
if ([string]::IsNullOrWhiteSpace($ReleaseVersion)) {
    Fail "O manifesto nao contem uma versao de release valida."
}

$VersionFile = Join-Path $Destination "jarvis_core\__init__.py"
if (-not (Test-Path -LiteralPath $VersionFile -PathType Leaf)) {
    Fail "jarvis_core\__init__.py em falta."
}
$VersionText = Get-Content -LiteralPath $VersionFile -Raw
$VersionMatch = [regex]::Match($VersionText, '__version__\s*=\s*["'']([^"'']+)["'']')
if (-not $VersionMatch.Success) {
    Fail "Nao consegui determinar a versao instalada do Core."
}
$CoreVersion = [string]$VersionMatch.Groups[1].Value
if ($CoreVersion -ne $ReleaseVersion) {
    Fail "Versao do Core ($CoreVersion) nao corresponde ao manifesto ($ReleaseVersion)."
}

Write-Host "=== JARVIS $ReleaseVersion - SECURITY BASELINE REPAIR ===" -ForegroundColor Cyan
Write-Host "1/6 A validar hashes antes de remover Mark-of-the-Web..."
foreach ($Item in $Manifest.files) {
    $Path = Join-Path $Destination $Item.path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Fail "Ficheiro da release em falta: $($Item.path)"
    }
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($Hash -ne ([string]$Item.sha256).ToLowerInvariant()) {
        Fail "Hash invalido; nao vou desbloquear: $($Item.path)"
    }
}

Write-Host "2/6 A remover MOTW apenas dos ficheiros verificados da release..."
$Unblocked = 0
foreach ($Item in $Manifest.files) {
    $Path = Join-Path $Destination $Item.path
    try {
        Unblock-File -LiteralPath $Path -ErrorAction Stop
        $Unblocked++
    } catch {
        Fail "Nao consegui remover MOTW de $($Item.path): $($_.Exception.Message)"
    }
}
Write-Host "  ficheiros verificados processados: $Unblocked" -ForegroundColor DarkGray

function Remove-PackageTolerant([string]$Package) {
    $old = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $out = & $Python -m pip uninstall -y $Package 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
    if ($code -ne 0) {
        Fail "pip uninstall falhou para $Package (exit $code): $(($out | Out-String).Trim())"
    }
}

Write-Host "3/6 A remover dependencias legacy associadas aos bloqueios antigos..."
$Legacy = @(
    'sherpa-onnx','sherpa-onnx-core','scipy','scikit-learn','av',
    'SpeechRecognition','vosk','pocketsphinx','pvporcupine','openai-whisper','whisper'
)
foreach ($pkg in $Legacy) { Remove-PackageTolerant $pkg }

# pip pode deixar um diretorio incompleto quando um binario foi bloqueado pelo
# Windows. Removemos apenas artefactos conhecidos da stack legacy dentro da
# .venv; nunca tocamos em logs, memory, modelos ou ficheiros do Core.
$SitePackages = Join-Path $Destination ".venv\Lib\site-packages"
if (Test-Path -LiteralPath $SitePackages) {
    $LegacyPatterns = @(
        'scipy','scipy-*.dist-info','scipy.libs',
        'sklearn','scikit_learn-*.dist-info',
        'sherpa_onnx','sherpa_onnx-*.dist-info','sherpa_onnx_core-*.dist-info',
        'av','av-*.dist-info'
    )
    foreach ($pattern in $LegacyPatterns) {
        Get-ChildItem -LiteralPath $SitePackages -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like $pattern } |
            ForEach-Object {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
                Write-Host "  removido resto legacy: $($_.Name)" -ForegroundColor DarkGray
            }
    }
}

$Forbidden = @(
    '*\scipy\sparse\_sparsetools*.pyd',
    '*\scipy\spatial\_ckdtree*.pyd',
    '*\sherpa_onnx\lib\_sherpa_onnx*.pyd',
    '*\av\*.pyd'
)
$Left = @()
if (Test-Path -LiteralPath $SitePackages) {
    foreach ($pattern in $Forbidden) {
        $Left += @(Get-ChildItem -LiteralPath $SitePackages -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like $pattern })
    }
}
if ($Left.Count -gt 0) {
    Fail "Ainda existem binarios legacy bloqueados: $((@($Left | ForEach-Object FullName) -join ', '))"
}

Write-Host "4/6 A validar a stack nativa de voz/STT atualmente usada..."
& $Python -c "import numpy, sounddevice, ctranslate2, onnxruntime, pyaudiowpatch; from jarvis_core.services.openwakeword_compat import runtime_classes; M,V=runtime_classes(); M(wakeword_models=['hey_jarvis'], inference_framework='onnx', vad_threshold=0.0); V(n_threads=1); from jarvis_core.services.stt_compat import probe_faster_whisper_pcm_import; r=probe_faster_whisper_pcm_import(); assert r.get('ok'), r; print('VOICE_STT_NATIVE_CURRENT: OK')"
if ($LASTEXITCODE -ne 0) { Fail "A stack nativa atual falhou a validacao." }

Write-Host "5/6 A validar o executavel do cerebro nativo JARVIS..."
$LlamaServer = Join-Path $Destination "runtime\llama.cpp\llama-server.exe"
if (Test-Path -LiteralPath $LlamaServer -PathType Leaf) {
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $LlamaProbe = & $LlamaServer --version 2>&1
        $LlamaCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldPreference
    }
    if ($LlamaCode -ne 0) {
        $CodeHex = Format-WindowsExitCode $LlamaCode
        $ProbeDetail = ((@($LlamaProbe) -join ' ').Trim())
        Write-Warning "llama-server standalone nao carrega (exit $LlamaCode / $CodeHex). O passo 6 vai verificar o executor local alternativo antes de decidir se isto e fatal. Detalhe: $ProbeDetail"
        Write-Host "  JARVIS_LLM_RUNTIME_CURRENT: NATIVE_UNAVAILABLE_PENDING_COMPAT_CHECK ($CodeHex)" -ForegroundColor Yellow
    }
    else {
        Write-Host "  JARVIS_LLM_RUNTIME_CURRENT: OK" -ForegroundColor Green
    }
}
else {
    Write-Host "  JARVIS_LLM_RUNTIME_CURRENT: NOT_INSTALLED (setup_native_brain deve correr antes deste baseline)" -ForegroundColor Yellow
}

Write-Host "6/6 A repetir Windows Block Audit com corroboracao atual..."
$AuditJson = & $Python -c "import json; from jarvis_core.services.windows_block_audit import audit_windows_blocked_files; r=audit_windows_blocked_files(save_report=True); print(json.dumps({'status':r.get('status'),'active':len(r.get('active_block_events') or []),'resolved':len(r.get('resolved_historical_block_events') or []),'historical_uncorroborated':len(r.get('historical_uncorroborated_block_events') or []),'mitigated':len(r.get('mitigated_block_events') or []),'native_failures':r.get('native_import_failures') or [],'llama_probe':r.get('native_llama_runtime_probe') or {},'local_executor':r.get('local_llm_executor_probe') or {},'motw':len(r.get('motw_current') or [])}))"
if ($LASTEXITCODE -ne 0) { Fail "Windows Block Audit falhou." }
$Audit = $AuditJson | ConvertFrom-Json
if ([int]$Audit.active -ne 0) {
    Write-Host ""
    Write-Host "Detalhe dos bloqueios atualmente corroborados:" -ForegroundColor Yellow
    & $Python -c "from jarvis_core.services.windows_block_audit import audit_windows_blocked_files,format_windows_block_audit; print(format_windows_block_audit(audit_windows_blocked_files(save_report=False), detail='full'))"
    Fail "Persistem $($Audit.active) bloqueios com evidencia atual. Os eventos historicos sem corroboracao nao contam como bloqueio ativo."
}
if (@($Audit.native_failures).Count -ne 0) {
    Fail "Persistem native import failures: $(@($Audit.native_failures) -join ', ')"
}
if ($Audit.llama_probe.installed -and -not $Audit.llama_probe.ok -and -not $Audit.local_executor.ok) {
    Fail "O probe atual do llama-server falhou e nao existe executor local alternativo saudavel: $($Audit.llama_probe.returncode_hex) $($Audit.llama_probe.error)"
}
if ($Audit.llama_probe.installed -and -not $Audit.llama_probe.ok -and $Audit.local_executor.ok) {
    Write-Host "JARVIS_LLM_RUNTIME_CURRENT: COMPAT_OK (native bloqueado; Ollama local/qwen3:8b como executor apenas)" -ForegroundColor Yellow
}
elseif ($Audit.llama_probe.ok) {
    Write-Host "JARVIS_LLM_RUNTIME_CURRENT: NATIVE_OK" -ForegroundColor Green
}

Write-Host "" 
Write-Host "SECURITY BASELINE: OK" -ForegroundColor Green
Write-Host "Bloqueios ativos : $($Audit.active)"
Write-Host "Resolvidos/hist. : $($Audit.resolved)"
Write-Host "Hist. sem corrob. : $($Audit.historical_uncorroborated)"
Write-Host "Mitigados         : $($Audit.mitigated)"
Write-Host "MOTW atual        : $($Audit.motw)"
Write-Host "Historico do Windows preservado; nenhum Event Log foi apagado." -ForegroundColor DarkGray
