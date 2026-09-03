param(
    [ValidateSet("Auto", "Windows", "WSL")]
    [string]$Mode = "Auto",
    [switch]$InstallWSL
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Executa primeiro .\setup.ps1" }

Write-Host "=== JARVIS 0.27.8 - VOICE LEARNING ENVIRONMENT ===" -ForegroundColor Cyan
Write-Host "Treino completo openWakeWord; runtime Windows continua protegido e leve."
Write-Host ""

$PolicyJson = & $Python -c "import json; from jarvis_core.services.windows_block_audit import audit_windows_blocked_files; r=audit_windows_blocked_files(save_report=True); ev=r.get('confirmed_block_events') or []; smart=any(bool(x.get('smart_app_control')) for x in ev); prefer=smart or r.get('status') == 'blocked'; print(json.dumps({'status':r.get('status'),'smart_app_control_detected':smart,'prefer_wsl':prefer,'active_blocks':len(r.get('active_block_events') or [])}))"
if ($LASTEXITCODE -ne 0) { throw "Não foi possível diagnosticar App Control." }
$Policy = $PolicyJson | ConvertFrom-Json
Write-Host ("App Control audit: " + $Policy.status)
Write-Host ("Smart App Control detetado nos eventos: " + $Policy.smart_app_control_detected)
Write-Host ("Bloqueios ativos relacionados com JARVIS: " + $Policy.active_blocks)

$Chosen = $Mode
if ($Mode -eq "Auto") {
    if ($Policy.prefer_wsl) { $Chosen = "WSL" }
    else { $Chosen = "Windows" }
}

function Setup-WindowsLearning {
    Write-Host "[Windows] A instalar stack completa de aprendizagem..." -ForegroundColor Cyan
    & $Python -m pip install --upgrade -r .\requirements-voice-learning.txt
    if ($LASTEXITCODE -ne 0) { return $false }
    & $Python -c "import scipy, sklearn, openwakeword; print('Windows learning stack: OK'); print('scipy', scipy.__version__); print('sklearn', sklearn.__version__)"
    return ($LASTEXITCODE -eq 0)
}

function Setup-WSLLearning {
    $Wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if (-not $Wsl) {
        if ($InstallWSL) {
            Write-Host "WSL não encontrado. A pedir instalação do Ubuntu..." -ForegroundColor Yellow
            & wsl.exe --install -d Ubuntu
            Write-Host "Reinicia o Windows se for solicitado e volta a executar este script." -ForegroundColor Yellow
            return $false
        }
        throw "WSL não está instalado. Executa novamente com -InstallWSL, ou instala WSL/Ubuntu pelo Windows e repete."
    }

    $Distros = @(& wsl.exe -l -q 2>$null | ForEach-Object { $_.Trim([char]0).Trim() } | Where-Object { $_ })
    if ($Distros.Count -eq 0) {
        if ($InstallWSL) {
            & wsl.exe --install -d Ubuntu
            Write-Host "Instalação do Ubuntu iniciada. Reinicia se necessário e repete." -ForegroundColor Yellow
            return $false
        }
        throw "WSL existe mas não há distribuição Linux. Executa com -InstallWSL."
    }

    $LinuxRoot = (& wsl.exe wslpath -a $PSScriptRoot | Select-Object -First 1).Trim()
    if (-not $LinuxRoot) { throw "Não foi possível converter o caminho atual do JARVIS para WSL." }

    $Script = @'
set -e
ENV="$HOME/.jarvis-voice-learning"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python3 não existe na distribuição WSL." >&2
  exit 31
fi
if [ ! -x "$ENV/.venv/bin/python" ]; then
  if ! python3 -m venv "$ENV/.venv"; then
    echo "Falhou python3 -m venv. No Ubuntu executa: sudo apt update && sudo apt install -y python3-venv" >&2
    exit 32
  fi
fi
"$ENV/.venv/bin/python" -m pip install --upgrade pip wheel setuptools
"$ENV/.venv/bin/python" -m pip install --upgrade "openwakeword==0.6.0" "scipy==1.17.1" "scikit-learn==1.8.0" "onnxruntime==1.29.0" "numpy==2.3.5" "tqdm==4.70.0" "requests==2.34.2"
"$ENV/.venv/bin/python" - <<'PY'
import scipy, sklearn, openwakeword
print("WSL learning stack: OK")
print("scipy", scipy.__version__)
print("sklearn", sklearn.__version__)
print("openwakeword", getattr(openwakeword, "__version__", "installed"))
PY
'@
    $Tmp = Join-Path $env:TEMP "jarvis_voice_learning_wsl.sh"
    Set-Content -LiteralPath $Tmp -Value $Script -Encoding ascii
    $LinuxTmp = (& wsl.exe wslpath -a $Tmp | Select-Object -First 1).Trim()
    & wsl.exe bash $LinuxTmp
    if ($LASTEXITCODE -ne 0) { return $false }
    return $true
}

$Ok = $false
if ($Chosen -eq "Windows") {
    if ($Policy.smart_app_control_detected) {
        throw "Smart App Control foi detetado neste PC. O treino com SciPy/scikit-learn nao sera reinstalado na .venv Windows; usa -Mode WSL para preservar a baseline de seguranca."
    }
    $Ok = Setup-WindowsLearning
    if (-not $Ok -and $Mode -eq "Auto") {
        Write-Host "A stack completa foi bloqueada no Windows. A mudar automaticamente para WSL sem reduzir a segurança." -ForegroundColor Yellow
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "diagnose_app_control.ps1")
        $Chosen = "WSL"
        $Ok = Setup-WSLLearning
    }
}
elseif ($Chosen -eq "WSL") {
    $Ok = Setup-WSLLearning
}

if (-not $Ok) { throw "O ambiente de aprendizagem não ficou pronto." }

& $Python -c "from jarvis_core.core.config import Settings; Settings.ensure_file_schema(); Settings.update_file_values({'voice_learning_backend':'$($Chosen.ToLower())'}); print('voice_learning_backend=$($Chosen.ToLower())')"
if ($LASTEXITCODE -ne 0) { throw "Falhou a gravação do backend de aprendizagem." }

Write-Host ""
Write-Host "Aprendizagem de voz pronta: $Chosen" -ForegroundColor Green
Write-Host "Próximo: .\collect_voice_learning.ps1"
Write-Host "Depois:  .\train_voice_learning.ps1"
