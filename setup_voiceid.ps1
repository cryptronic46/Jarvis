$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Executa primeiro .\setup.ps1 -SkipModel" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== JARVIS VOICE LOCK SETUP (CAM++ TorchScript) ==="

Write-Host "A instalar PyTorch CPU + Torchaudio..."
& ".\.venv\Scripts\python.exe" -m pip install --upgrade `
    torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao instalar PyTorch/Torchaudio."
}

$modelDir = Join-Path (Get-Location) "models\voiceid"
$modelName = "3d_speaker-speech_campplus_sv_en_voxceleb_16k.pt"
$modelPath = Join-Path $modelDir $modelName
$modelUrl = "https://github.com/k2-fsa/sherpa/releases/download/speaker-recognition-models/$modelName"
$expectedSha256 = "8ebcd0b04c1bb50d5fe77166f9a123206bf08ed14bcfd6a0b95fe8fcb2e25926"

New-Item -ItemType Directory -Path $modelDir -Force | Out-Null

$needsDownload = $true
if (Test-Path $modelPath) {
    $existingHash = (Get-FileHash -Algorithm SHA256 $modelPath).Hash.ToLower()
    if ($existingHash -eq $expectedSha256) {
        Write-Host "Modelo CAM++ já existe e o SHA-256 está correto." -ForegroundColor Green
        $needsDownload = $false
    } else {
        Write-Host "Modelo existente tem hash incorreto; vou voltar a descarregar." -ForegroundColor Yellow
        Remove-Item $modelPath -Force
    }
}

if ($needsDownload) {
    Write-Host "A descarregar CAM++ VoxCeleb (~30 MB)..."
    Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath -UseBasicParsing

    if (-not (Test-Path $modelPath)) {
        throw "O download do modelo Voice Lock falhou."
    }

    $actualSha256 = (Get-FileHash -Algorithm SHA256 $modelPath).Hash.ToLower()
    if ($actualSha256 -ne $expectedSha256) {
        Remove-Item $modelPath -Force -ErrorAction SilentlyContinue
        throw "SHA-256 do modelo inválido. O ficheiro foi eliminado."
    }
}

Write-Host "A testar imports do Voice Lock..."
& ".\.venv\Scripts\python.exe" -c "import torch; import torchaudio.compliance.kaldi; print('PyTorch', torch.__version__, '| Voice Lock deps OK')"
if ($LASTEXITCODE -ne 0) {
    throw "PyTorch/Torchaudio não carregaram corretamente."
}

Write-Host ""
Write-Host "Voice Lock CAM++ instalado e verificado." -ForegroundColor Green
Write-Host "Inicia com .\run.ps1 e executa /voiceid doctor"
