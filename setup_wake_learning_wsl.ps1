param(
    [string]$PositiveDir = "",
    [string]$NegativeDir = "",
    [string]$Output = "",
    [string]$Distro = ""
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PositiveDir)) { $PositiveDir = Join-Path $PSScriptRoot "voice_profiles\wake_learning\positive" }
if ([string]::IsNullOrWhiteSpace($NegativeDir)) { $NegativeDir = Join-Path $PSScriptRoot "voice_profiles\wake_learning\negative" }
if ([string]::IsNullOrWhiteSpace($Output)) { $Output = Join-Path $PSScriptRoot "models\wake_verifier_jarvis.npz" }
if ($env:OS -ne "Windows_NT") { throw "Este launcher e dirigido ao Windows com WSL." }
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "WSL nao esta disponivel. Instala/ativa WSL antes do treino personalizado." 
}
New-Item -ItemType Directory -Force -Path $PositiveDir, $NegativeDir, (Split-Path -Parent $Output) | Out-Null
$positiveCount = @(Get-ChildItem -LiteralPath $PositiveDir -Filter *.wav -File -ErrorAction SilentlyContinue).Count
$negativeCount = @(Get-ChildItem -LiteralPath $NegativeDir -Filter *.wav -File -ErrorAction SilentlyContinue).Count
if ($positiveCount -lt 3 -or $negativeCount -lt 1) {
    Write-Host "Dados insuficientes para treino." -ForegroundColor Yellow
    Write-Host "Positivos: $positiveCount (minimo 3) em $PositiveDir"
    Write-Host "Negativos: $negativeCount (minimo 1; >=10s de fala e recomendado) em $NegativeDir"
    throw "Recolhe primeiro os clips de treino." 
}

function To-WslPath([string]$WindowsPath) {
    $WslArgs = @("wslpath", "-u", "-a", $WindowsPath)
    if ($Distro) { $out = & wsl.exe -d $Distro -- @WslArgs } else { $out = & wsl.exe -- @WslArgs }
    if ($LASTEXITCODE -ne 0) { throw "Falhou conversao WSL path: $WindowsPath" }
    return ($out | Select-Object -First 1).Trim()
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Trainer = Join-Path $Root "jarvis_core\services\train_wake_verifier_wsl.py"
$posWsl = To-WslPath $PositiveDir
$negWsl = To-WslPath $NegativeDir
$outWsl = To-WslPath $Output
$trainerWsl = To-WslPath $Trainer

Write-Host "=== JARVIS Wake Learning (WSL isolated trainer) ===" -ForegroundColor Cyan
Write-Host "Windows App Control permanece ativo. SciPy/scikit-learn correm apenas dentro do Linux/WSL."
$bootstrap = @'
set -e
command -v python3 >/dev/null || { echo "python3 nao esta instalado na distro WSL"; exit 21; }
python3 -m venv ~/.jarvis-wake-learning || { echo "python3-venv pode estar em falta na distro WSL"; exit 22; }
. ~/.jarvis-wake-learning/bin/activate
python -m pip install --upgrade pip
python -m pip install "openwakeword==0.6.0" "scipy==1.17.1" "scikit-learn==1.8.0" "onnxruntime==1.29.0" "tqdm==4.70.0"
'@
if ($Distro) { & wsl.exe -d $Distro -- bash -lc $bootstrap } else { & wsl.exe -- bash -lc $bootstrap }
if ($LASTEXITCODE -ne 0) { throw "Falhou preparacao do ambiente WSL de aprendizagem." }

$cmd = ". ~/.jarvis-wake-learning/bin/activate && python '$trainerWsl' --positive-dir '$posWsl' --negative-dir '$negWsl' --output '$outWsl'"
if ($Distro) { & wsl.exe -d $Distro -- bash -lc $cmd } else { & wsl.exe -- bash -lc $cmd }
if ($LASTEXITCODE -ne 0) { throw "Falhou treino/exportacao do wake verifier." }

Write-Host "Wake verifier treinado e exportado para: $Output" -ForegroundColor Green
Write-Host "O runtime Windows usa apenas NumPy para este verifier; SciPy/sklearn nao sao necessarios para inferencia."
