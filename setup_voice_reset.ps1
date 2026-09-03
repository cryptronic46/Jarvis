param(
    [string]$SttModel = "small",
    [switch]$SkipSttModelDownload
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Executa primeiro .\setup.ps1 -SkipModel" }
Write-Host "=== JARVIS 0.27.8 - VOICE RESET ===" -ForegroundColor Cyan

function Remove-PythonPackageIfPresent {
    param([Parameter(Mandatory=$true)][string]$Package)

    # pip writes harmless "WARNING: Skipping ... not installed" messages to
    # stderr. With $ErrorActionPreference=Stop Windows PowerShell can turn
    # those warnings into NativeCommandError and abort the whole reset.
    # For optional cleanup only, tolerate stderr and trust pip's exit code.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $Python -m pip uninstall -y $Package 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    if ($exitCode -ne 0) {
        $detail = ($output | Out-String).Trim()
        throw "Falhou a remocao opcional do pacote '$Package' (exit code $exitCode). $detail"
    }

    $removed = $false
    foreach ($line in @($output)) {
        $text = [string]$line
        if ($text -match 'Successfully uninstalled') { $removed = $true }
    }
    if ($removed) {
        Write-Host "  removido: $Package" -ForegroundColor DarkGray
    } else {
        Write-Host "  ausente:  $Package" -ForegroundColor DarkGray
    }
}

Write-Host "A remover stacks antigas de input/STT que ja nao pertencem ao runtime..."
$old = @('sherpa-onnx','sherpa-onnx-core','scikit-learn','scipy','SpeechRecognition','vosk','pocketsphinx','pvporcupine','openai-whisper','whisper')
foreach ($pkg in $old) { Remove-PythonPackageIfPresent -Package $pkg }
# Reinstall the minimal stack. openWakeWord is inference-only; ONNX avoids TFLite.
& $Python -m pip install --upgrade -r .\requirements-voice-v2.txt
if ($LASTEXITCODE -ne 0) { throw "Falhou a instalacao da stack base de voz." }
& $Python -m pip install --upgrade --no-deps openwakeword==0.6.0
if ($LASTEXITCODE -ne 0) { throw "Falhou openWakeWord." }
& $Python -m pip install --upgrade faster-whisper==1.2.1
if ($LASTEXITCODE -ne 0) { throw "Falhou faster-whisper." }
# PyAV is not used for microphone PCM and has been blocked by Smart App Control on this machine.
Remove-PythonPackageIfPresent -Package 'av'
Write-Host "A validar Silero/openWakeWord ONNX + Faster-Whisper PCM..."
& $Python -c "from jarvis_core.services.openwakeword_compat import runtime_classes; M,V=runtime_classes(); m=M(wakeword_models=['hey_jarvis'], inference_framework='onnx', vad_threshold=0.0); V(n_threads=1); from jarvis_core.services.stt_compat import probe_faster_whisper_pcm_import; assert probe_faster_whisper_pcm_import()['ok']; print('VAD + openWakeWord + Faster-Whisper PCM: OK')"
if ($LASTEXITCODE -ne 0) { throw "Voice Reset runtime nao passou a validacao." }
if (-not $SkipSttModelDownload) {
  New-Item -ItemType Directory -Force -Path '.\models\faster-whisper' | Out-Null
  & $Python -c "from jarvis_core.services.stt_compat import load_whisper_model_class; W=load_whisper_model_class(); W('$SttModel', device='cpu', compute_type='int8', download_root='models/faster-whisper'); print('Faster Whisper $SttModel cached')"
  if ($LASTEXITCODE -ne 0) { throw "Falhou cache do Faster-Whisper." }
}
New-Item -ItemType Directory -Force -Path '.\models\openwakeword' | Out-Null
& $Python -c "from jarvis_core.core.config import Settings; Settings.ensure_file_schema(); Settings.update_file_values({'voice_input_backend':'v2','voice_v2_wake_threshold':0.45,'voice_v2_wake_vad_threshold':0.35,'voice_v2_wake_confirm_frames':1,'voice_v2_wake_strong_threshold':0.45,'voice_v2_stt_model':'$SttModel','voice_v2_stt_device':'cpu','voice_v2_owner_semantic_confirm':False}); print('Voice Reset settings aplicados')"
Write-Host "Voice Reset concluido." -ForegroundColor Green
Write-Host "Wake custom opcional: coloca um modelo openWakeWord ONNX em models\openwakeword\jarvis.onnx."
Write-Host "Sem modelo custom, usa o modelo oficial hey_jarvis."
