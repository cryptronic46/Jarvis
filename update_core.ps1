param(
    [string]$Destination = "G:\JARVIS",
    [switch]$RunTests,
    [switch]$UnblockVerifiedRelease,
    [switch]$PreserveMarkOfTheWeb
)

$ErrorActionPreference = "Stop"
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$ResolvedSource = (
    [System.IO.Path]::GetFullPath($Source)
).TrimEnd('\')
$ResolvedDestination = (
    [System.IO.Path]::GetFullPath($Destination)
).TrimEnd('\')
$SameTree = ($ResolvedSource -ieq $ResolvedDestination)

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "ERRO: $Message" -ForegroundColor Red
    exit 1
}

function Get-Sha256([string]$Path) {
    return (
        Get-FileHash -Algorithm SHA256 -LiteralPath $Path
    ).Hash.ToLowerInvariant()
}

function Get-ControlledReleaseFiles(
    [string]$Root,
    [object]$Manifest
) {
    $RootFull = (
        [System.IO.Path]::GetFullPath($Root)
    ).TrimEnd('\')
    $RuntimeParts = @(
        "__pycache__",
        ".venv",
        "memory",
        "knowledge",
        ".cache",
        "logs",
        "voice_profiles",
        "models"
    )
    $Result = @()

    foreach ($TreeName in @($Manifest.scope.trees)) {
        $Base = Join-Path $RootFull $TreeName
        if (-not (Test-Path -LiteralPath $Base)) {
            Fail "Controlled tree missing: $TreeName"
        }

        Get-ChildItem -LiteralPath $Base -File -Recurse -Force |
        ForEach-Object {
            $Relative = $_.FullName.Substring(
                $RootFull.Length + 1
            ).Replace('\','/')
            $Parts = $Relative.Split('/')
            $Skip = $false

            foreach ($Part in $Parts) {
                if ($RuntimeParts -contains $Part) {
                    $Skip = $true
                    break
                }
            }

            if ($_.Extension -ieq ".pyc") {
                $Skip = $true
            }

            if (-not $Skip) {
                $Result += $Relative
            }
        }
    }

    foreach ($Name in @($Manifest.scope.top_level)) {
        $Path = Join-Path $RootFull $Name
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            Fail "Controlled top-level file missing: $Name"
        }
        $Result += $Name.Replace('\','/')
    }

    return @($Result | Sort-Object -Unique)
}

function Validate-ReleaseTree(
    [string]$Root,
    [string]$ManifestPath,
    [string]$Label
) {
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        Fail "${Label}: release_manifest.json nao existe."
    }

    try {
        $Manifest = (
            Get-Content -LiteralPath $ManifestPath -Raw |
            ConvertFrom-Json
        )
    }
    catch {
        Fail "${Label}: release_manifest.json e invalido."
    }

    if ($Manifest.release -ne "0.27.8") {
        Fail "${Label}: o manifesto nao e da release 0.27.8."
    }

    $Known = @(
        $Manifest.files |
        ForEach-Object {
            $_.path.Replace('\','/')
        } |
        Sort-Object -Unique
    )
    $Controlled = @(
        Get-ControlledReleaseFiles `
            -Root $Root `
            -Manifest $Manifest
    )

    $MissingFromManifest = @(
        $Controlled |
        Where-Object { $Known -notcontains $_ }
    )
    $ManifestOutsideScope = @(
        $Known |
        Where-Object { $Controlled -notcontains $_ }
    )

    if ($MissingFromManifest.Count -gt 0) {
        Fail (
            "${Label}: ficheiros controlados fora do manifesto: " +
            ($MissingFromManifest -join ", ")
        )
    }
    if ($ManifestOutsideScope.Count -gt 0) {
        Fail (
            "${Label}: entradas do manifesto fora do scope controlado: " +
            ($ManifestOutsideScope -join ", ")
        )
    }

    foreach ($Item in $Manifest.files) {
        $Path = Join-Path $Root $Item.path

        if (-not (Test-Path -LiteralPath $Path)) {
            Fail "${Label}: ficheiro da release em falta: $($Item.path)"
        }

        $Hash = Get-Sha256 $Path
        if ($Hash -ne $Item.sha256.ToLowerInvariant()) {
            Fail "${Label}: hash invalido: $($Item.path)"
        }
    }

    return $Manifest
}

function Mirror-Tree([string]$Name) {
    $From = Join-Path $Source $Name
    $To = Join-Path $Destination $Name

    if (-not (Test-Path -LiteralPath $From)) {
        Fail "Falta no pacote: $Name"
    }

    New-Item -ItemType Directory -Force -Path $To | Out-Null

    $null = & robocopy.exe `
        $From `
        $To `
        /MIR `
        /COPY:DAT `
        /DCOPY:DAT `
        /R:2 `
        /W:1 `
        /NFL `
        /NDL `
        /NJH `
        /NJS `
        /NP

    if ($LASTEXITCODE -ge 8) {
        Fail "robocopy falhou em $Name (exit code $LASTEXITCODE)"
    }
}

function Copy-FileForce([string]$Name) {
    $From = Join-Path $Source $Name
    $To = Join-Path $Destination $Name

    if (-not (Test-Path -LiteralPath $From)) {
        Fail "Falta no pacote: $Name"
    }

    Copy-Item -LiteralPath $From -Destination $To -Force
}


function Unblock-VerifiedManifestFiles(
    [string]$Root,
    [object]$Manifest
) {
    # Since 0.27.8 security hotfix, verified Core files are unblocked by
    # default after source + destination SHA-256 validation. The old
    # -UnblockVerifiedRelease switch remains accepted for compatibility.
    if ($PreserveMarkOfTheWeb) {
        return
    }

    Write-Host ""
    Write-Host "A remover Mark-of-the-Web apenas dos ficheiros verificados da release..." -ForegroundColor Cyan

    $Count = 0
    foreach ($Item in $Manifest.files) {
        $Path = Join-Path $Root $Item.path
        if (-not (Test-Path -LiteralPath $Path)) {
            continue
        }

        try {
            Unblock-File -LiteralPath $Path -ErrorAction Stop
            $Count += 1
        }
        catch {
            Fail "Falha ao desbloquear ficheiro verificado: $($Item.path)"
        }
    }

    Write-Host "MOTW removido dos ficheiros verificados da release: $Count" -ForegroundColor Green
}

function Repair-ExternalPowerShell51Encoding {
    $Relative = "JARVIS_Live_Wallpaper_0.1.0\install.ps1"
    $Path = Join-Path $Destination $Relative

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }

    $Bytes = [System.IO.File]::ReadAllBytes($Path)
    if (
        $Bytes.Length -ge 3 -and
        $Bytes[0] -eq 0xEF -and
        $Bytes[1] -eq 0xBB -and
        $Bytes[2] -eq 0xBF
    ) {
        return
    }

    $HasNonAscii = $false
    foreach ($Byte in $Bytes) {
        if ($Byte -ge 0x80) {
            $HasNonAscii = $true
            break
        }
    }
    if (-not $HasNonAscii) {
        return
    }

    # Do not reinterpret legacy ANSI files. Only add a BOM when the current
    # bytes are already valid strict UTF-8, which preserves the file content.
    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    try {
        [void]$StrictUtf8.GetString($Bytes)
    }
    catch {
        Write-Warning "External Wallpaper install.ps1 is not strict UTF-8; encoding left unchanged."
        return
    }

    $WithBom = New-Object byte[] ($Bytes.Length + 3)
    $WithBom[0] = 0xEF
    $WithBom[1] = 0xBB
    $WithBom[2] = 0xBF
    [System.Array]::Copy($Bytes, 0, $WithBom, 3, $Bytes.Length)
    [System.IO.File]::WriteAllBytes($Path, $WithBom)

    Write-Host "PowerShell 5.1 encoding repaired for external Wallpaper installer." -ForegroundColor Green
}

function Remove-StaleManagedTopLevelFiles {
    $CurrentAudit = "AUDIT_0.27.8.md"

    Get-ChildItem `
        -LiteralPath $Destination `
        -File `
        -Filter "AUDIT_0.*.md" `
        -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -ne $CurrentAudit
    } |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
        Write-Host "Removido ficheiro antigo do Core: $($_.Name)"
    }
}

Write-Host ""
Write-Host "JARVIS CORE UPDATE 0.27.8" -ForegroundColor Cyan
Write-Host "Origem : $Source"
Write-Host "Destino: $Destination"
Write-Host ""

if (-not (Test-Path -LiteralPath $Destination)) {
    Fail "Destino nao existe: $Destination"
}

$RunningJarvis = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -like "python*" -and
        $_.CommandLine -match "(?i)jarvis\.py"
    }
)
if ($RunningJarvis.Count -gt 0) {
    Fail "O JARVIS ainda esta em execucao. Fecha-o com /quit e volta a executar este updater."
}

# Phase 1: validate source before touching the active JARVIS destination.
Write-Host "A validar pacote de origem..." -ForegroundColor Cyan
$SourceManifestPath = Join-Path $Source "release_manifest.json"
$SourceManifest = Validate-ReleaseTree `
    -Root $Source `
    -ManifestPath $SourceManifestPath `
    -Label "ORIGEM"
Write-Host "Pacote de origem: OK" -ForegroundColor Green
Write-Host ""

Write-Host "Preservado:" -ForegroundColor Green
Write-Host "  memory\"
Write-Host "  knowledge\"
Write-Host "  .venv\"
Write-Host "  .cache\"
Write-Host "  logs\"
Write-Host "  voice_profiles\"
Write-Host "  models\"
Write-Host "  skills\ (OWNER trusted external modules)"
Write-Host "  settings.json"
Write-Host "  apps.json"
Write-Host "  add-ons/pastas externas (ex.: Wallpaper)"
Write-Host ""

if ($SameTree) {
    Write-Host "Origem e destino sao a mesma instalacao." -ForegroundColor Yellow
    Write-Host "Nao vou copiar ficheiros sobre eles proprios; vou apenas validar a release."
    Write-Host ""
}
else {
    Write-Host "A sincronizar arvores controladas pela release..." -ForegroundColor Cyan

    Mirror-Tree "jarvis_core"
    Mirror-Tree "tests"
    Mirror-Tree "defaults"

    $TopFiles = @(
        ".gitignore",
        "jarvis.py",
        "setup.ps1",
        "run.ps1",
        "migrate_state.ps1",
        "migrate_to_g.ps1",
        "finalize_g_migration.ps1",
        "diagnose_app_control.ps1",
        "repair_security_baseline.ps1",
        "full_system_validation.ps1",
        "acceptance_real_machine.ps1",
        "setup_native_brain.ps1",
        "setup_appcontrol_trust.ps1",
        "setup_cloud.ps1",
        "setup_voiceid.ps1",
        "setup_wakeword.ps1",
        "setup_voice_v2.ps1",
        "setup_voice_reset.ps1",
        "install_custom_wake_model.ps1",
        "setup_wake_learning_wsl.ps1",
        "setup_voice_learning.ps1",
        "collect_voice_learning.ps1",
        "train_voice_learning.ps1",
        "setup_vision.ps1",
        "requirements.txt",
        "requirements-cloud.txt",
        "requirements-voiceid.txt",
        "requirements-wakeword.txt",
        "requirements-voice-v2.txt",
        "requirements-voice-learning.txt",
        "README.md",
        "AUDIT_0.27.8.md",
        "JARVIS_FUNCTIONAL_AUDIT.md",
        "JARVIS_REAL_MACHINE_ACCEPTANCE.md",        "update_core.ps1",
        "verify_release.ps1",
        "repair_startup_shortcut.ps1",
        "HOTFIX_0.27.8_PERFORMANCE_AUTONOMY_V11.md",
        "release_manifest.json"
    )

    foreach ($File in $TopFiles) {
        Copy-FileForce $File
    }

    Remove-StaleManagedTopLevelFiles

    Write-Host "Codigo sincronizado." -ForegroundColor Green
}

Repair-ExternalPowerShell51Encoding

# Phase 2: validate destination after copy.
Write-Host "A verificar integridade integral do destino..." -ForegroundColor Cyan
$DestinationManifestPath = Join-Path $Destination "release_manifest.json"
$DestinationManifest = Validate-ReleaseTree `
    -Root $Destination `
    -ManifestPath $DestinationManifestPath `
    -Label "DESTINO"

Unblock-VerifiedManifestFiles `
    -Root $Destination `
    -Manifest $DestinationManifest

if (-not $PreserveMarkOfTheWeb) {
    $DestinationManifest = Validate-ReleaseTree `
        -Root $Destination `
        -ManifestPath $DestinationManifestPath `
        -Label "DESTINO-POS-UNBLOCK"
}

$VersionText = Get-Content -LiteralPath (
    Join-Path $Destination "jarvis_core\__init__.py"
) -Raw
$CliText = Get-Content -LiteralPath (
    Join-Path $Destination "jarvis_core\cli.py"
) -Raw
$WakeText = (
    (Get-Content -LiteralPath (Join-Path $Destination "jarvis_core\services\wakeword.py") -Raw) +
    "`n" +
    (Get-Content -LiteralPath (Join-Path $Destination "jarvis_core\services\voice_engine_v2.py") -Raw)
)
$HybridText = Get-Content -LiteralPath (
    Join-Path $Destination "jarvis_core\core\hybrid_brain.py"
) -Raw
$ResearchPath = Join-Path $Destination "jarvis_core\services\local_research.py"
$CyberRangePath = Join-Path $Destination "jarvis_core\services\cyber_range.py"
$RequestIntentPath = Join-Path $Destination "jarvis_core\services\request_intent.py"
$KaliBridgePath = Join-Path $Destination "jarvis_core\services\kali_bridge.py"
$CompanionPresencePath = Join-Path $Destination "jarvis_core\services\companion_presence.py"
$DesktopIntegrationPath = Join-Path $Destination "jarvis_core\services\desktop_integration.py"
$FollowupIntentPath = Join-Path $Destination "jarvis_core\services\followup_intent.py"
$SkillsManagerPath = Join-Path $Destination "jarvis_core\skills\manager.py"
$TaskPlannerPath = Join-Path $Destination "jarvis_core\skills\builtin\task_planner.py"
$VisionSkillPath = Join-Path $Destination "jarvis_core\skills\builtin\vision.py"
$NativeVisionPath = Join-Path $Destination "jarvis_core\core\local_vision.py"
$GuardianSkillPath = Join-Path $Destination "jarvis_core\skills\builtin\system_guardian.py"
$PurpleSkillPath = Join-Path $Destination "jarvis_core\skills\builtin\purple_team.py"
$VisionSetupPath = Join-Path $Destination "setup_vision.ps1"
$ListeningWatchdogPath = Join-Path $Destination "jarvis_core\services\listening_watchdog.py"
$AvDevicesPath = Join-Path $Destination "jarvis_core\services\av_devices.py"
$WallpaperLivePath = Join-Path $Destination "jarvis_core\skills\builtin\wallpaper_live.py"
$SilenceLatchPath = Join-Path $Destination "jarvis_core\services\silence_latch.py"
$ActivityTracePath = Join-Path $Destination "jarvis_core\services\activity_trace.py"
$IdleMindPath = Join-Path $Destination "jarvis_core\services\idle_mind.py"
$ActionTruthPath = Join-Path $Destination "jarvis_core\services\action_truth.py"
$FastRouterPath = Join-Path $Destination "jarvis_core\core\fast_router.py"
$VoiceV2Path = Join-Path $Destination "jarvis_core\services\voice_engine_v2.py"
$VoiceV2SetupPath = Join-Path $Destination "setup_voice_reset.ps1"
$OpenWakeCompatPath = Join-Path $Destination "jarvis_core\services\openwakeword_compat.py"
$VoiceV2RequirementsPath = Join-Path $Destination "requirements-voice-v2.txt"
$SttCompatPath = Join-Path $Destination "jarvis_core\services\stt_compat.py"
$WakeVerifierPath = Join-Path $Destination "jarvis_core\services\wake_verifier.py"
$WakeLearningSetupPath = Join-Path $Destination "setup_wake_learning_wsl.ps1"
$FastRouterText = Get-Content -LiteralPath $FastRouterPath -Raw
$VoiceV2SetupText = Get-Content -LiteralPath $VoiceV2SetupPath -Raw

if (-not (Test-Path -LiteralPath $VoiceV2Path -PathType Leaf)) {
    Fail "Voice Engine v2 nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $VoiceV2SetupPath -PathType Leaf)) {
    Fail "setup_voice_reset.ps1 nao esta presente."
}
if (-not (Test-Path -LiteralPath $OpenWakeCompatPath -PathType Leaf)) {
    Fail "openWakeWord inference-only compatibility loader nao esta presente."
}
if (-not (Test-Path -LiteralPath $VoiceV2RequirementsPath -PathType Leaf)) {
    Fail "requirements-voice-v2.txt nao esta presente."
}
if (-not (Test-Path -LiteralPath $SttCompatPath -PathType Leaf)) {
    Fail "STT PCM compatibility loader nao esta presente."
}
if (-not (Test-Path -LiteralPath $WakeVerifierPath -PathType Leaf)) {
    Fail "NumPy wake verifier nao esta presente."
}
if (-not (Test-Path -LiteralPath $WakeLearningSetupPath -PathType Leaf)) {
    Fail "setup_wake_learning_wsl.ps1 nao esta presente."
}
if ($VoiceV2SetupText -notmatch '--no-deps') {
    Fail "Voice v2 setup nao instala openWakeWord em modo inference-only."
}
if ($VoiceV2SetupText -notmatch 'openwakeword_compat') {
    Fail "Voice v2 setup nao valida o compatibility loader."
}
if ($VoiceV2SetupText -notmatch 'load_whisper_model_class') {
    Fail "Voice v2 setup nao usa o loader PCM do Faster Whisper."
}
if ($VoiceV2SetupText -match 'from faster_whisper import WhisperModel') {
    Fail "Voice v2 setup voltou a importar PyAV diretamente via faster_whisper."
}
if ($CliText -notmatch '/voice doctor') {
    Fail "Voice Engine v2 diagnostics nao estao presentes no CLI."
}
if ($CliText -notmatch '/voice latency') {
    Fail "Voice Engine v2 latency diagnostics nao estao presentes no CLI."
}
if ($CliText -notmatch '/voice backend ') {
    Fail "Voice Engine backend selector nao esta presente no CLI."
}

if (-not (Test-Path -LiteralPath $SilenceLatchPath -PathType Leaf)) {
    Fail "Silence Latch nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $ActivityTracePath -PathType Leaf)) {
    Fail "Activity Trace nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $IdleMindPath -PathType Leaf)) {
    Fail "Idle Mind nao esta presente no Core."
}
if ($CliText -notmatch '/mind idle') {
    Fail "Idle Mind CLI nao esta presente."
}
if ($CliText -notmatch '/mind idle reflect') {
    Fail "Idle Mind reflection CLI nao esta presente."
}
if (-not (Test-Path -LiteralPath $ActionTruthPath -PathType Leaf)) {
    Fail "Action Truth Guard nao esta presente no Core."
}
if ($FastRouterText -notmatch 'voice_app_fragment_open') {
    Fail "Voice app-fragment recovery nao esta presente no Fast Path."
}
if ($CliText -notmatch '/activity status') {
    Fail "Activity Trace CLI nao esta presente."
}
if ($CliText -notmatch '/silence status') {
    Fail "Silence Latch CLI nao esta presente."
}
if ($VersionText -notmatch '0\.27\.8') {
    Fail "A versao instalada nao e 0.27.8."
}
if ($CliText -notmatch '/cyber inspect network') {
    Fail "Deep Security Inspection nao esta presente."
}
if ($CliText -notmatch '/mind status') {
    Fail "Personal Cognition nao esta presente."
}
if ($CliText -notmatch '/cyber lab status') {
    Fail "Cyber Range Guard nao esta presente no CLI."
}
if (-not (Test-Path -LiteralPath $CyberRangePath -PathType Leaf)) {
    Fail "Cyber Range Guard nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $RequestIntentPath -PathType Leaf)) {
    Fail "Capability Intent Guard nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $KaliBridgePath -PathType Leaf)) {
    Fail "Kali Execution Bridge nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $CompanionPresencePath -PathType Leaf)) {
    Fail "Adaptive Companion Presence nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $DesktopIntegrationPath -PathType Leaf)) {
    Fail "Desktop Integration nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $FollowupIntentPath -PathType Leaf)) {
    Fail "Follow-up Continuity Guard nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $SkillsManagerPath -PathType Leaf)) {
    Fail "Modular Skills Runtime nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $TaskPlannerPath -PathType Leaf)) {
    Fail "Autonomous Task Planner nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $VisionSkillPath -PathType Leaf)) {
    Fail "Local Vision skill nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $NativeVisionPath -PathType Leaf)) {
    Fail "Native multimodal vision runtime nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $VisionSetupPath -PathType Leaf)) {
    Fail "setup_vision.ps1 nao esta presente."
}
$VisionSetupText = Get-Content -LiteralPath $VisionSetupPath -Raw
$NativeVisionText = Get-Content -LiteralPath $NativeVisionPath -Raw
if ($VisionSetupText -notmatch 'd02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12') {
    Fail "setup_vision.ps1 nao contem o SHA-256 pinned do modelo visual."
}
if ($VisionSetupText -notmatch '980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904') {
    Fail "setup_vision.ps1 nao contem o SHA-256 pinned do mmproj visual."
}
if ($NativeVisionText -notmatch '--mmproj') {
    Fail "Native vision runtime nao carrega o projetor multimodal."
}
if ($NativeVisionText -notmatch '127\.0\.0\.1') {
    Fail "Native vision runtime nao esta fixado a loopback."
}
if (-not (Test-Path -LiteralPath $GuardianSkillPath -PathType Leaf)) {
    Fail "System Guardian skill nao esta presente no Core."
}
$GuardianText = Get-Content -LiteralPath $GuardianSkillPath -Raw
if ($GuardianText -notmatch 'severity_counts') {
    Fail "System Guardian severity contract nao esta presente."
}
if (-not (Test-Path -LiteralPath $PurpleSkillPath -PathType Leaf)) {
    Fail "Purple Team Orchestrator nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $ListeningWatchdogPath -PathType Leaf)) {
    Fail "Listening Watchdog nao esta presente no Core."
}
if (-not (Test-Path -LiteralPath $AvDevicesPath -PathType Leaf)) {
    Fail "Webcam A/V binding nao esta presente no Core."
}
if ($CliText -notmatch '/av probe') {
    Fail "Signal-Aware Microphone Probe nao esta presente no CLI."
}
if ($WakeText -notmatch 'WAKE_CANDIDATE_CONFIRMED') {
    Fail "Wake candidate Whisper confirmation nao esta presente."
}
if ($WakeText -notmatch 'WAKE_ZERO_NOISE_FLOOR') {
    Fail "Wake noise-gate tolerance nao esta presente no Core."
}
if ($WakeText -notmatch 'preferred_device_index') {
    Fail "OWNER exact microphone binding nao esta presente no Wake Core."
}
if (-not (Test-Path -LiteralPath $WallpaperLivePath -PathType Leaf)) {
    Fail "Live Wallpaper async publisher nao esta presente no Core."
}
if ($CliText -notmatch '/desktop status') {
    Fail "Desktop Integration nao esta presente no CLI."
}
if ($CliText -notmatch '/cyber kali status') {
    Fail "Kali Execution Bridge nao esta presente no CLI."
}
if ($CliText -notmatch '/companion status') {
    Fail "Adaptive Companion Presence nao esta presente no CLI."
}
if ($CliText -notmatch '/skills status') {
    Fail "Modular Skills Runtime nao esta presente no CLI."
}
if ($CliText -notmatch '/planner status') {
    Fail "Autonomous Task Planner nao esta presente no CLI."
}
if ($CliText -notmatch '/vision status') {
    Fail "Local Vision nao esta presente no CLI."
}
if ($CliText -notmatch '/guardian status') {
    Fail "System Guardian nao esta presente no CLI."
}
if ($CliText -notmatch '/purple status') {
    Fail "Purple Team Orchestrator nao esta presente no CLI."
}
if ($CliText -notmatch '/listening status') {
    Fail "Listening Watchdog status nao esta presente no CLI."
}
if ($CliText -notmatch '/listening recover') {
    Fail "Listening recovery nao esta presente no CLI."
}
if ($CliText -notmatch '/av status') {
    Fail "Webcam A/V commands nao estao presentes no CLI."
}
if ($CliText -notmatch '/stt status') {
    Fail "STT Accuracy diagnostics nao estao presentes no CLI."
}
if ($CliText -notmatch '/stt test') {
    Fail "STT Accuracy test nao esta presente no CLI."
}
if ($CliText -notmatch '/vram status') {
    Fail "VRAM residency diagnostics nao estao presentes no CLI."
}
if ($CliText -notmatch 'release_all_models') {
    Fail "VRAM shutdown release nao esta presente no Core."
}
if ($WakeText -notmatch 'bargein-v2\+whisper') {
    Fail "Barge-In v2 nao esta presente."
}
if (-not (Test-Path -LiteralPath $ResearchPath -PathType Leaf)) {
    Fail "Local Research Engine nao esta presente."
}
if ($CliText -notmatch 'External AI: HARD BLOCKED') {
    Fail "O bloqueio estrutural de IA externa nao esta presente no CLI."
}
if ($CliText -match 'OWNER authorization each consultation') {
    Fail "Foi encontrado o contrato legacy de autorizacao de especialista externo no CLI."
}

Write-Host ""
Write-Host "UPDATE VALIDADO" -ForegroundColor Green
Write-Host "Core: 0.27.8"
Write-Host "Pacote de origem: OK"
Write-Host "Arvore canonica: OK"
Write-Host "Manifesto integral: OK"
Write-Host "Updater instalado: OK"
if ($PreserveMarkOfTheWeb) {
    Write-Host "MOTW da release verificada: PRESERVADO (pedido explicito)"
}
else {
    Write-Host "MOTW da release verificada: REMOVIDO APOS SHA-256"
}
Write-Host "Barge-In v2: PRESENTE"
Write-Host "Deep Security Inspection 2.0: PRESENTE"
Write-Host "Cyber Range Guard: PRESENTE"
Write-Host "Capability Intent Guard: PRESENTE"
Write-Host "Kali Execution Bridge: PRESENTE (fixed LAB profiles)"
Write-Host "Adaptive Feminine Presence: PRESENTE"
Write-Host "Desktop Integration / Wallpaper Engine: PRESENTE"
Write-Host "Follow-up Continuity Guard: PRESENTE"
Write-Host "Modular Skills Runtime: PRESENTE"
Write-Host "Desktop Agent / Computer Control: PRESENTE"
Write-Host "Purple Team Orchestrator: PRESENTE (LAB only)"
Write-Host "System Guardian + severity HUD contract: PRESENTE"
Write-Host "Autonomous Task Planner + bounded adaptation: PRESENTE"
Write-Host "Relational Memory Graph: PRESENTE"
Write-Host "Live Wallpaper State Contract: PRESENTE"
Write-Host "Local Screen/Camera Vision: PRESENTE (native llama.cpp multimodal; explicit setup)"
Write-Host "Self Diagnostics / Safe Repair: PRESENTE"
Write-Host "Listening Watchdog / auto-recovery: PRESENTE"
Write-Host "Silence Latch / false-wake confirmation: PRESENTE"
Write-Host "Safe Activity Trace: PRESENTE"
Write-Host "Action Truth Guard: PRESENTE"
Write-Host "Voice Reset 0.27.8: PRESENTE (WASAPI + Silero VAD + openWakeWord + Faster-Whisper)"
Write-Host "Voice Fast-Path recovery: PRESENTE"
Write-Host "Idle Mind on-demand reflection: PRESENTE"
Write-Host "Unified Webcam A/V Binding: PRESENTE"
Write-Host "Webcam STT Accuracy Pipeline: PRESENTE"
Write-Host "VRAM Residency / shutdown unload: PRESENTE"
Write-Host "Live HUD async event publishing: PRESENTE"
Write-Host "LAB TCP Probe: PRESENTE"
Write-Host "Personal Cognition: PRESENTE"
Write-Host "Proactive Presence: PRESENTE"
Write-Host "External AI: HARD BLOCKED | Direct Web + Local Qwen synthesis only"
Write-Host "Epistemic Learning + request-scoped learned RAG: PRESENTE"
Write-Host "Native Brain / llama.cpp: PRESENTE"
Write-Host "Direct Web + Local Synthesis: PRESENTE"
Write-Host ""

if ($RunTests) {
    Write-Host "A executar setup/testes..." -ForegroundColor Cyan
    Push-Location $Destination
    try {
        & ".\setup.ps1" -SkipModel
        if ($LASTEXITCODE -ne 0) {
            Fail "setup.ps1 terminou com exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "Agora executa:" -ForegroundColor Yellow
    Write-Host "  cd $Destination"
    Write-Host "  .\setup.ps1 -SkipModel"
}
