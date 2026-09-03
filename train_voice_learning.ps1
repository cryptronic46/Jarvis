param(
    [string]$PositiveDir = "memory\voice_learning\positive",
    [string]$NegativeDir = "memory\voice_learning\negative",
    [string]$OutputPath = "models\wakeword\custom\jarvis_verifier.npz"
)
$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Python da JARVIS não encontrado." }

$Backend = & $Python -c "from jarvis_core.core.config import Settings; print(Settings.load().voice_learning_backend)"
$Backend = ($Backend | Select-Object -Last 1).Trim().ToLower()
if (-not $Backend) { $Backend = "auto" }

$PosCandidate = $(if ([System.IO.Path]::IsPathRooted($PositiveDir)) { $PositiveDir } else { Join-Path $PSScriptRoot $PositiveDir })
$NegCandidate = $(if ([System.IO.Path]::IsPathRooted($NegativeDir)) { $NegativeDir } else { Join-Path $PSScriptRoot $NegativeDir })
$Pos = (Resolve-Path -LiteralPath $PosCandidate).Path
$Neg = (Resolve-Path -LiteralPath $NegCandidate).Path
$OutParent = Split-Path -Parent (Join-Path $PSScriptRoot $OutputPath)
New-Item -ItemType Directory -Force -Path $OutParent | Out-Null
$Out = Join-Path $PSScriptRoot $OutputPath

if ($Backend -eq "windows") {
    & $Python -m jarvis_core.learning.train_voice_verifier --positive-dir $Pos --negative-dir $Neg --output $Out
    if ($LASTEXITCODE -ne 0) { throw "Treino Windows falhou. Executa .\diagnose_app_control.ps1; se houver bloqueio usa .\setup_voice_learning.ps1 -Mode WSL." }
}
else {
    $LinuxRoot = (& wsl.exe wslpath -a $PSScriptRoot | Select-Object -First 1).Trim()
    $LinuxPos = (& wsl.exe wslpath -a $Pos | Select-Object -First 1).Trim()
    $LinuxNeg = (& wsl.exe wslpath -a $Neg | Select-Object -First 1).Trim()
    $LinuxOut = (& wsl.exe wslpath -a $Out | Select-Object -First 1).Trim()
    $Trainer = "$LinuxRoot/jarvis_core/learning/train_voice_verifier.py"
    & wsl.exe bash -lc "~/.jarvis-voice-learning/.venv/bin/python '$Trainer' --positive-dir '$LinuxPos' --negative-dir '$LinuxNeg' --output '$LinuxOut'"
    if ($LASTEXITCODE -ne 0) { throw "Treino WSL falhou. Executa .\setup_voice_learning.ps1 -Mode WSL." }
}

& $Python -c "from jarvis_core.services.voice_learning import load_numpy_verifier; import json; m=load_numpy_verifier(r'$Out'); print(json.dumps({'ok': bool(m), 'path': r'$Out', 'feature_count': (m or {}).get('feature_count')}, ensure_ascii=False))"
if ($LASTEXITCODE -ne 0) { throw "O modelo treinado não pôde ser validado no runtime Windows NumPy-only." }
Write-Host "Verificador personalizado pronto. Reinicia o JARVIS para o Voice Engine v2 o carregar." -ForegroundColor Green
