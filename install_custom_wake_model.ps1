param([Parameter(Mandatory=$true)][string]$ModelPath)
$ErrorActionPreference='Stop'; Set-Location -LiteralPath $PSScriptRoot
if(-not (Test-Path -LiteralPath $ModelPath)){throw "Modelo nao encontrado: $ModelPath"}
if([IO.Path]::GetExtension($ModelPath).ToLower() -ne '.onnx'){throw 'O modelo deve ser .onnx'}
New-Item -ItemType Directory -Force -Path '.\models\openwakeword' | Out-Null
Copy-Item -LiteralPath $ModelPath -Destination '.\models\openwakeword\jarvis.onnx' -Force
Write-Host 'Modelo custom Jarvis instalado. Reinicia o JARVIS.' -ForegroundColor Green
