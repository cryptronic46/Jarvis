param([switch]$SkipModel)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][scriptblock]$Command,
        [Parameter(Mandatory=$true)][string]$Label
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "ERRO: $Label falhou (exit code $LASTEXITCODE)." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

$versionLine = Get-Content ".\jarvis_core\__init__.py" | Select-String '__version__'
$version = (($versionLine -split '"')[1])

Write-Host ""
Write-Host "=== JARVIS CORE $version - SETUP ==="
Write-Host ""

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "ERRO: Python nao foi encontrado no PATH." -ForegroundColor Red
    exit 1
}

# Remove stale tests left behind by older releases when users extract over the same folder.
# The release manifest is the single source of truth. Do not maintain a second hardcoded test list.
$ManifestPath = ".\release_manifest.json"
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    Write-Host "ERRO: release_manifest.json nao foi encontrado." -ForegroundColor Red
    exit 1
}

try {
    $ReleaseManifest = (
        Get-Content -LiteralPath $ManifestPath -Raw |
        ConvertFrom-Json
    )
}
catch {
    Write-Host "ERRO: release_manifest.json e invalido." -ForegroundColor Red
    exit 1
}

function Confirm-AndUnblockVerifiedRelease {
    param(
        [Parameter(Mandatory=$true)][object]$Manifest
    )

    $ManifestRelease = [string]$Manifest.release
    if ($ManifestRelease -ne $version) {
        Write-Host "ERRO: manifesto ($ManifestRelease) e Core ($version) nao correspondem." -ForegroundColor Red
        exit 1
    }

    Write-Host "A validar SHA-256 dos ficheiros controlados antes de remover MOTW..."
    foreach ($Item in $Manifest.files) {
        $Path = Join-Path $PSScriptRoot $Item.path
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            Write-Host "ERRO: ficheiro controlado em falta: $($Item.path)" -ForegroundColor Red
            exit 1
        }
        $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
        if ($Hash -ne ([string]$Item.sha256).ToLowerInvariant()) {
            Write-Host "ERRO: hash invalido; MOTW preservado: $($Item.path)" -ForegroundColor Red
            exit 1
        }
    }

    Write-Host "A remover MOTW apenas dos ficheiros verificados da release..."
    foreach ($Item in $Manifest.files) {
        $Path = Join-Path $PSScriptRoot $Item.path
        Unblock-File -LiteralPath $Path -ErrorAction Stop
    }

    # Unblock-File changes only the Zone.Identifier alternate stream, never
    # the file bytes. Recheck hashes so nested setup scripts only run after
    # a second integrity confirmation.
    foreach ($Item in $Manifest.files) {
        $Path = Join-Path $PSScriptRoot $Item.path
        $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
        if ($Hash -ne ([string]$Item.sha256).ToLowerInvariant()) {
            Write-Host "ERRO: hash alterado apos Unblock-File: $($Item.path)" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "Release verificada e desbloqueada: $ManifestRelease" -ForegroundColor Green
}

Confirm-AndUnblockVerifiedRelease -Manifest $ReleaseManifest

$expectedTests = @(
    $ReleaseManifest.files |
    ForEach-Object {
        $Normalized = $_.path.Replace('\','/')
        if ($Normalized -like 'tests/test_*.py') {
            ($Normalized -split '/')[-1]
        }
    } |
    Where-Object { $_ } |
    Sort-Object -Unique
)

if ($expectedTests.Count -eq 0) {
    Write-Host "ERRO: o manifesto nao contem testes controlados." -ForegroundColor Red
    exit 1
}

if (Test-Path ".\tests") {
    Get-ChildItem ".\tests\test_*.py" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($expectedTests -notcontains $_.Name) {
            Write-Host "A remover teste obsoleto: $($_.Name)"
            Remove-Item $_.FullName -Force
        }
    }
    Get-ChildItem ".\tests" -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
}
Get-ChildItem "." -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem "." -File -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue | Remove-Item -Force

if (-not (Test-Path ".venv")) {
    Write-Host "A criar ambiente virtual..."
    Invoke-Checked { python -m venv .venv } "criacao do ambiente virtual"
}


Write-Host "A atualizar dependencias..."
Invoke-Checked { & ".\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip } "pip upgrade"
Invoke-Checked { & ".\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade -r requirements.txt } "instalacao das dependencias"

Write-Host "A sincronizar schema de settings.json..."
Invoke-Checked {
    & ".\.venv\Scripts\python.exe" -c "from jarvis_core.core.config import Settings; r=Settings.ensure_file_schema(); print('Settings adicionados:', r['added_count'])"
} "migracao do settings.json"

Write-Host "A aplicar politica 0.27.8 JARVIS LEARNING-FIRST (executor local adaptativo)..."
# App Control enforcement by JARVIS is retired in this hotfix. Historical
# trust-state files are deliberately ignored so a stale 'enforced' marker can
# never disable the compatibility executor or reintroduce policy coupling.
$AllowCompat = $true
$AllowCompatPython = 'True'
Invoke-Checked {
    & ".\.venv\Scripts\python.exe" -c "from jarvis_core.core.config import Settings; Settings.update_file_values({'local_llm_backend':'jarvis_local','local_llm_allow_ollama_compat':$AllowCompatPython,'hybrid_mode':'local','cloud_fallback_on_local_error':False,'external_ai_enabled':False,'cloud_enabled':False,'expert_escalation_enabled':False,'external_ai_auto_escalate_complex':False,'performance_cloud_offload_under_pressure':False,'performance_release_llm_on_pressure':False,'voice_v2_preload_stt':True}); print('JARVIS local-only AI policy: enabled; external AI HARD BLOCKED; web->local synthesis; ollama_compat=$AllowCompatPython')"
} "politica JARVIS local-only"

Write-Host "A consolidar a stack minima de voz..."
Invoke-Checked { & ".\setup_voice_reset.ps1" -SkipSttModelDownload } "voice reset minimo"

Write-Host "A preparar cerebro local JARVIS (Qwen3; CUDA -> Vulkan -> compat local se necessario)..."
if ($SkipModel) {
    Invoke-Checked { & ".\setup_native_brain.ps1" -SkipModelDownload } "setup native brain"
}
else {
    Invoke-Checked { & ".\setup_native_brain.ps1" } "setup native brain"
}

# Security baseline is intentionally evaluated AFTER the local brain executor
# has been installed/repaired. Windows Event Log is historical; probing the
# current executor is required before deciding that an old 3077/8004/8007
# event still represents a present blocker.
Write-Host "A reparar/verificar baseline de seguranca..."
Invoke-Checked { & ".\repair_security_baseline.ps1" -Destination $PSScriptRoot } "security baseline repair"

Write-Host ""
Write-Host "A executar testes do Core $version..."
Invoke-Checked { & ".\.venv\Scripts\python.exe" -m unittest discover -s tests -q } "testes do JARVIS"

Write-Host ""
Write-Host "Setup do JARVIS Core $version concluido com sucesso." -ForegroundColor Green
Write-Host "Executa: .\run.ps1"
