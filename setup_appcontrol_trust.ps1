param(
    [ValidateSet('Status','Observe','Plan','Audit','Enforce','Prepare')]
    [string]$Mode = 'Status',
    [switch]$ConfirmMigration
)

$ErrorActionPreference = 'Stop'
Write-Host '=== JARVIS 0.27.8 - WINDOWS APP CONTROL OBSERVE-ONLY ===' -ForegroundColor Cyan
Write-Host 'Este hotfix NÃO cria, instala, atualiza, remove ou ativa políticas WDAC/App Control.' -ForegroundColor Green
Write-Host 'O nome deste script é mantido apenas por compatibilidade com releases anteriores.' -ForegroundColor DarkGray

if ($Mode -notin @('Status','Observe')) {
    Write-Host ("Modo '{0}' desativado: a JARVIS não tem capacidade de enforcement." -f $Mode) -ForegroundColor Yellow
}

if (Test-Path -LiteralPath '.\diagnose_app_control.ps1') {
    & '.\diagnose_app_control.ps1'
    exit $LASTEXITCODE
}

Write-Host 'diagnose_app_control.ps1 não encontrado; nenhuma alteração foi efetuada.' -ForegroundColor Yellow
exit 0
