param(
    [switch]$SkipCamera,
    [switch]$SkipModel
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ModelDir = Join-Path $Root "models\vision"

$Repo = "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF"
$Revision = "5037fcf163dd95d1e41d1974465f0898ed108ca2"
$ModelName = "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
$MmprojName = "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"
$ModelSha256 = "d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12"
$MmprojSha256 = "980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904"

function Assert-Sha256([string]$Path, [string]$Expected, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label em falta: $Path"
    }
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected.ToLowerInvariant()) {
        throw "$Label com SHA-256 invalido. Esperado=$Expected Atual=$Actual"
    }
    Write-Host "[JARVIS/VISION] $Label SHA-256: OK" -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "JARVIS virtual environment not found. Run .\setup.ps1 first."
}

if (-not $SkipCamera) {
    Write-Host "[JARVIS/VISION] A validar OpenCV local..." -ForegroundColor Cyan
    & $Python -m pip install --disable-pip-version-check -q opencv-python==4.14.0.94
    if ($LASTEXITCODE -ne 0) { throw "OpenCV installation failed." }
}

New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null
$ModelPath = Join-Path $ModelDir $ModelName
$MmprojPath = Join-Path $ModelDir $MmprojName

if (-not $SkipModel) {
    $NeedModel = $true
    if (Test-Path -LiteralPath $ModelPath -PathType Leaf) {
        try {
            Assert-Sha256 $ModelPath $ModelSha256 "Modelo visual"
            $NeedModel = $false
        }
        catch {
            Write-Warning $_.Exception.Message
            Remove-Item -LiteralPath $ModelPath -Force -ErrorAction SilentlyContinue
        }
    }

    $NeedMmproj = $true
    if (Test-Path -LiteralPath $MmprojPath -PathType Leaf) {
        try {
            Assert-Sha256 $MmprojPath $MmprojSha256 "Projetor multimodal"
            $NeedMmproj = $false
        }
        catch {
            Write-Warning $_.Exception.Message
            Remove-Item -LiteralPath $MmprojPath -Force -ErrorAction SilentlyContinue
        }
    }

    if ($NeedModel -or $NeedMmproj) {
        Write-Host "[JARVIS/VISION] A descarregar o modelo multimodal local verificado (~2.8 GB)..." -ForegroundColor Cyan
        Write-Host "[JARVIS/VISION] Fonte: Hugging Face / ggml-org; inferencia posterior e 100% local." -ForegroundColor DarkGray
        $env:JARVIS_VISION_MODEL_DIR = $ModelDir
        $env:JARVIS_VISION_REPO = $Repo
        $env:JARVIS_VISION_REVISION = $Revision
        $env:JARVIS_VISION_MODEL_FILE = $ModelName
        $env:JARVIS_VISION_MMPROJ_FILE = $MmprojName

        $DownloadCode = @'
import os
from huggingface_hub import hf_hub_download
root = os.environ["JARVIS_VISION_MODEL_DIR"]
repo = os.environ["JARVIS_VISION_REPO"]
revision = os.environ["JARVIS_VISION_REVISION"]
for filename in (os.environ["JARVIS_VISION_MODEL_FILE"], os.environ["JARVIS_VISION_MMPROJ_FILE"]):
    path = hf_hub_download(
        repo_id=repo,
        filename=filename,
        revision=revision,
        local_dir=root,
    )
    print("[JARVIS/VISION] downloaded: " + str(path))
'@
        $DownloadHelper = Join-Path ([System.IO.Path]::GetTempPath()) ("jarvis_vision_download_" + [guid]::NewGuid().ToString("N") + ".py")
        try {
            $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($DownloadHelper, $DownloadCode, $Utf8NoBom)
            & $Python $DownloadHelper
            if ($LASTEXITCODE -ne 0) {
                throw "Falha ao descarregar o modelo visual local."
            }
        }
        finally {
            Remove-Item -LiteralPath $DownloadHelper -Force -ErrorAction SilentlyContinue
        }
    }

    Assert-Sha256 $ModelPath $ModelSha256 "Modelo visual"
    Assert-Sha256 $MmprojPath $MmprojSha256 "Projetor multimodal"
}
else {
    Write-Host "[JARVIS/VISION] Download do modelo ignorado por -SkipModel." -ForegroundColor Yellow
}

$env:JARVIS_VISION_ROOT = $Root
$SettingsCode = @'
import json
import os
from pathlib import Path

root = Path(os.environ["JARVIS_VISION_ROOT"])
path = root / "settings.json"
if path.is_file():
    data = json.loads(path.read_text(encoding="utf-8-sig"))
else:
    data = {}

updates = {
    "vision_enabled": True,
    "vision_model": "Qwen2.5-VL-3B-Instruct-Q4_K_M",
    "vision_native_model_path": "models/vision/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
    "vision_native_mmproj_path": "models/vision/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf",
    "vision_native_port": 11436,
}
data.update(updates)

tmp = path.with_name(path.name + ".vision.tmp")
try:
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
finally:
    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass

print({"ok": True, "path": str(path), "changed": updates, "changed_count": len(updates)})
'@
$SettingsHelper = Join-Path ([System.IO.Path]::GetTempPath()) ("jarvis_vision_settings_" + [guid]::NewGuid().ToString("N") + ".py")
try {
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($SettingsHelper, $SettingsCode, $Utf8NoBom)
    & $Python $SettingsHelper
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao atualizar settings.json para a visão nativa."
    }
}
finally {
    Remove-Item -LiteralPath $SettingsHelper -Force -ErrorAction SilentlyContinue
    Remove-Item Env:JARVIS_VISION_ROOT -ErrorAction SilentlyContinue
}

$RuntimePath = Join-Path $Root "runtime\llama.cpp\llama-server.exe"
if (-not (Test-Path -LiteralPath $RuntimePath -PathType Leaf)) {
    throw "llama-server nativo nao encontrado. Executa .\setup_native_brain.ps1 primeiro."
}

if (-not $SkipModel) {
    Assert-Sha256 $ModelPath $ModelSha256 "Modelo visual"
    Assert-Sha256 $MmprojPath $MmprojSha256 "Projetor multimodal"
}

Write-Host "" 
Write-Host "JARVIS NATIVE VISION: READY" -ForegroundColor Green
Write-Host "Captura local         : READY"
Write-Host "Modelo                : Qwen2.5-VL-3B-Instruct Q4_K_M"
Write-Host "Backend               : llama.cpp nativo / loopback 127.0.0.1:11436"
Write-Host "External AI           : HARD BLOCKED"
Write-Host "Inferencia de imagens : LOCAL ONLY"
Write-Host "O runtime visual sera iniciado apenas quando uma analise de imagem for pedida."
