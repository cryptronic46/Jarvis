param(
    [ValidateSet('Prepare','Plan','Audit','Status','Disarm','Rollback')]
    [string]$Mode = 'Plan',
    [string]$Destination = $PSScriptRoot,
    [switch]$RebuildPlan
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$PolicyName = 'JARVIS App Control Observe-Only 0.27.8'
$LegacyJarvisPolicyIds = @(
    '{3923ff78-eba0-4270-a28d-e82a66c531d4}',
    '{3ac0a4b7-9a65-41df-8751-8cbd46949270}'
)
$KnownSacPolicyId = '{0283ac0f-fff1-49ae-ada1-8a933130cad6}'
$SacRegistryPath = 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy'
$SacRegistryValue = 'VerifiedAndReputablePolicyState'
$RuntimeDir = Join-Path $Destination 'runtime\llama.cpp'
$ServerPath = Join-Path $RuntimeDir 'llama-server.exe'
$ImplPath = Join-Path $RuntimeDir 'llama-server-impl.dll'
$ProvenancePath = Join-Path $RuntimeDir 'jarvis_runtime_provenance.json'
$StateDir = Join-Path $Destination 'memory\security\appcontrol'
$PlanPath = Join-Path $StateDir 'jarvis_appcontrol_trust_plan.json'
$StatePath = Join-Path $StateDir 'jarvis_appcontrol_trust_state.json'
$AuditXml = Join-Path $StateDir 'JARVIS_SAC_Derived_Audit.xml'
$AuditCip = Join-Path $StateDir 'JARVIS_SAC_Derived_Audit.cip'
$TemplatePath = Join-Path $env:windir 'schemas\CodeIntegrity\ExamplePolicies\SmartAppControl.xml'

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Fail([string]$Message) {
    Write-Host ''
    Write-Host ('ERRO: ' + $Message) -ForegroundColor Red
    exit 1
}

function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Require-Administrator {
    if (-not (Test-Administrator)) {
        Fail 'Este modo requer Windows PowerShell elevado (Executar como administrador).'
    }
}

function Get-SacState {
    try {
        $value = Get-ItemPropertyValue -Path $SacRegistryPath -Name $SacRegistryValue -ErrorAction Stop
        return [int]$value
    }
    catch { return -1 }
}

function Get-CiToolPath {
    $cmd = Get-Command CiTool.exe -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { Fail 'CiTool.exe nao existe. Esta funcionalidade requer Windows 11 22H2 ou superior.' }
    return $cmd.Source
}

function Invoke-CiTool([string[]]$Arguments) {
    $tool = Get-CiToolPath
    & $tool @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ('CiTool falhou: ' + ($Arguments -join ' ') + ' (exit ' + $LASTEXITCODE + ')')
    }
}

function Invoke-CiToolBestEffort([string[]]$Arguments) {
    try {
        $tool = Get-CiToolPath
        & $tool @Arguments | Out-Host
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        Write-Warning ('CiTool best-effort falhou: ' + $_.Exception.Message)
        return $false
    }
}

function Try-Get-CiPolicies {
    $tool = Get-CiToolPath
    $raw = & $tool -lp -json 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    try { return @((($raw -join "`n") | ConvertFrom-Json).Policies) }
    catch { return $null }
}

function Get-CiPolicies {
    $policies = Try-Get-CiPolicies
    if ($null -eq $policies) { Fail 'Nao foi possivel listar as politicas App Control com CiTool. Em Windows Pro, repete este modo numa PowerShell como Administrador.' }
    return @($policies)
}

function Test-PolicyPresent([string]$PolicyId) {
    $wanted = Normalize-Guid $PolicyId
    $matches = @(Get-CiPolicies | Where-Object { (Normalize-Guid ([string]$_.PolicyID)) -eq $wanted })
    return ($matches.Count -gt 0)
}

function Normalize-Guid([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    return ('{' + ([guid]($Value.Trim('{}'))).ToString() + '}').ToLowerInvariant()
}

function Get-PolicyIdFromXml([string]$Path) {
    [xml]$xml = Get-Content -LiteralPath $Path -Raw
    $node = $xml.SelectSingleNode("//*[local-name()='PolicyID']")
    if ($null -eq $node -or [string]::IsNullOrWhiteSpace($node.InnerText)) {
        Fail ('PolicyID em falta em ' + $Path)
    }
    return (Normalize-Guid $node.InnerText)
}

function Remove-ConditionalWindowsLockdownOption([string]$Path) {
    [xml]$xml = Get-Content -LiteralPath $Path -Raw
    $nodes = @($xml.SelectNodes("//*[local-name()='Rule'][*[local-name()='Option' and text()='Enabled:Conditional Windows Lockdown Policy']]") )
    foreach ($node in $nodes) {
        [void]$node.ParentNode.RemoveChild($node)
    }
    $xml.Save($Path)
    $check = Get-Content -LiteralPath $Path -Raw
    if ($check -match 'Conditional Windows Lockdown Policy') {
        Fail 'Nao foi possivel remover a opcao Conditional Windows Lockdown Policy do template SAC.'
    }
}

function Get-RuntimeFiles {
    if (-not (Test-Path -LiteralPath $RuntimeDir -PathType Container)) {
        Fail ('Runtime llama.cpp em falta: ' + $RuntimeDir)
    }
    $files = @(Get-ChildItem -LiteralPath $RuntimeDir -File -Recurse -ErrorAction Stop |
        Where-Object { $_.Extension -in @('.exe','.dll') } |
        Sort-Object FullName)
    if ($files.Count -eq 0) { Fail 'Nao existem EXE/DLL no runtime llama.cpp para autorizar.' }
    if (-not (Test-Path -LiteralPath $ServerPath -PathType Leaf)) { Fail 'llama-server.exe em falta.' }
    if (-not (Test-Path -LiteralPath $ImplPath -PathType Leaf)) { Fail 'llama-server-impl.dll em falta.' }
    return $files
}

function Assert-RuntimeProvenance {
    if (-not (Test-Path -LiteralPath $ProvenancePath -PathType Leaf)) {
        Fail 'Provenance do runtime em falta. Executa primeiro .\setup_native_brain.ps1 -RepairRuntime.'
    }
    try { $prov = Get-Content -LiteralPath $ProvenancePath -Raw | ConvertFrom-Json }
    catch { Fail 'jarvis_runtime_provenance.json e invalido.' }
    if ([string]$prov.installed_by -ne 'JARVIS') { Fail 'Runtime nao foi instalado pela cadeia verificada da JARVIS.' }
    if ([string]$prov.llama_cpp_tag -ne 'b10516') { Fail ('Runtime nao corresponde ao tag aprovado b10516: ' + [string]$prov.llama_cpp_tag) }
    if ([string]$prov.security -ne 'sha256_verified_then_unblocked') {
        Fail ('Runtime provenance nao confirma SHA-256 antes do Unblock-File: ' + [string]$prov.security)
    }
    return $prov
}

function Get-RuntimeInventory {
    $prov = Assert-RuntimeProvenance
    $files = Get-RuntimeFiles
    $entries = @()
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($RuntimeDir.Length).TrimStart('\').Replace('\','/')
        $entries += [ordered]@{
            path = $relative
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
            size = [int64]$file.Length
        }
    }

    $recorded = @($prov.runtime_file_hashes)
    if ($recorded.Count -eq 0) {
        Fail 'O runtime foi instalado antes do inventario SHA-256 por ficheiro. Executa .\setup_appcontrol_trust.ps1 -Mode Prepare para reinstalar apenas o runtime CUDA verificado (nao descarrega o modelo).'
    }
    $expected = @{}
    foreach ($item in $recorded) { $expected[[string]$item.path] = [string]$item.sha256 }
    if ($expected.Count -ne $entries.Count) { Fail 'O conjunto atual de EXE/DLL difere do inventario criado apos a verificacao do arquivo oficial.' }
    foreach ($item in $entries) {
        if (-not $expected.ContainsKey([string]$item.path)) { Fail ('Binario atual nao consta da provenance verificada: ' + [string]$item.path) }
        if ($expected[[string]$item.path] -ne [string]$item.sha256) { Fail ('Binario alterado depois da instalacao verificada: ' + [string]$item.path) }
    }
    return [pscustomobject]@{
        provenance = $prov
        files = $entries
    }
}

function Assert-InventoryMatchesPlan([object]$Plan) {
    $now = Get-RuntimeInventory
    $expected = @{}
    foreach ($item in @($Plan.runtime_files)) { $expected[[string]$item.path] = [string]$item.sha256 }
    $current = @{}
    foreach ($item in @($now.files)) { $current[[string]$item.path] = [string]$item.sha256 }
    if ($expected.Count -ne $current.Count) { Fail 'O conjunto de binarios do runtime mudou desde o plano de confianca.' }
    foreach ($path in $expected.Keys) {
        if (-not $current.ContainsKey($path)) { Fail ('Binario aprovado desapareceu: ' + $path) }
        if ($current[$path] -ne $expected[$path]) { Fail ('Hash alterado desde a aprovacao: ' + $path) }
    }
}

function Ensure-ConfigCI {
    if (-not (Get-Module -ListAvailable -Name ConfigCI)) { Fail 'Modulo ConfigCI nao esta disponivel neste Windows.' }
    Import-Module ConfigCI -ErrorAction Stop
    foreach ($name in @('New-CIPolicyRule','Merge-CIPolicy','Set-CIPolicyIdInfo','Set-CIPolicyVersion','Set-RuleOption','ConvertFrom-CIPolicy')) {
        if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { Fail ('Cmdlet ConfigCI em falta: ' + $name) }
    }
}

function Build-PolicyArtifacts {
    Ensure-ConfigCI
    if (-not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
        Fail ('Template oficial SmartAppControl.xml nao encontrado: ' + $TemplatePath)
    }
    $inventory = Get-RuntimeInventory
    Copy-Item -LiteralPath $TemplatePath -Destination $AuditXml -Force
    Remove-ConditionalWindowsLockdownOption $AuditXml

    # Turn the Microsoft Smart App Control example into our own base policy.
    Set-CIPolicyIdInfo -FilePath $AuditXml -PolicyName $PolicyName -ResetPolicyID | Out-Null
    Set-CIPolicyVersion -FilePath $AuditXml -Version '1.0.27.8'
    if ((Get-Content -LiteralPath $AuditXml -Raw) -notmatch 'Enabled:Audit Mode') { Set-RuleOption -FilePath $AuditXml -Option 3 }
    if ((Get-Content -LiteralPath $AuditXml -Raw) -notmatch 'Enabled:Unsigned System Integrity Policy') { Set-RuleOption -FilePath $AuditXml -Option 6 }
    if ((Get-Content -LiteralPath $AuditXml -Raw) -notmatch 'Enabled:Update Policy No Reboot') { Set-RuleOption -FilePath $AuditXml -Option 16 }

    # ConfigCI accepts String[] for DriverFilePath on supported Windows 11 builds.
    # Build all exact runtime paths first so Code Integrity performs one scan instead
    # of restarting the catalogue/signature scan for every individual DLL/EXE.
    $runtimePaths = @(
        foreach ($item in @($inventory.files)) {
            $full = Join-Path $RuntimeDir ([string]$item.path).Replace('/','\')
            if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
                Fail ('Ficheiro do inventario nao encontrado: ' + $full)
            }
            $full
        }
    )
    if ($runtimePaths.Count -eq 0) { Fail 'O inventario do runtime JARVIS esta vazio.' }

    $driverFilePathType = (Get-Command New-CIPolicyRule -ErrorAction Stop).Parameters['DriverFilePath'].ParameterType
    if ($driverFilePathType -ne [string[]]) {
        Fail ('Esta versao do ConfigCI nao suporta criacao Hash em lote. DriverFilePath=' + $driverFilePathType.FullName)
    }

    Write-Host ('[JARVIS/TRUST] A criar regras Hash em lote para ' + $runtimePaths.Count + ' ficheiros...') -ForegroundColor Cyan
    $rawRules = New-CIPolicyRule -Level Hash -DriverFilePath $runtimePaths

    # Some ConfigCI builds surface the returned Rule[] as one pipeline object.
    # Flatten explicitly before Merge-CIPolicy so -Rules receives Rule[], not
    # Object[]{ Rule[] } (which fails conversion on Windows 11).
    $rules = @(
        $rawRules | ForEach-Object {
            if ($_ -is [System.Array]) {
                foreach ($rule in $_) { $rule }
            }
            else { $_ }
        }
    )
    if ($rules.Count -eq 0) { Fail 'Nenhuma regra Hash foi criada para o runtime JARVIS.' }

    $rulesParameterType = (Get-Command Merge-CIPolicy -ErrorAction Stop).Parameters['Rules'].ParameterType
    $expectedRuleType = $rulesParameterType.GetElementType()
    if ($null -eq $expectedRuleType) {
        Fail ('Nao foi possivel determinar o tipo Rule esperado por Merge-CIPolicy. Tipo=' + $rulesParameterType.FullName)
    }
    foreach ($rule in $rules) {
        if (-not $expectedRuleType.IsInstanceOfType($rule)) {
            Fail ('New-CIPolicyRule devolveu tipo inesperado: ' + $rule.GetType().FullName)
        }
    }
    Write-Host ('[JARVIS/TRUST] Regras Hash normalizadas: ' + $rules.Count) -ForegroundColor Cyan

    $merged = Join-Path $StateDir 'JARVIS_SAC_Derived_Audit_Merged.xml'
    Write-Host ('[JARVIS/TRUST] A incorporar ' + $rules.Count + ' regras Hash em lote...') -ForegroundColor Cyan
    Merge-CIPolicy -PolicyPaths $AuditXml -OutputFilePath $merged -Rules $rules
    Move-Item -LiteralPath $merged -Destination $AuditXml -Force
    Set-CIPolicyVersion -FilePath $AuditXml -Version '1.0.27.8'
    ConvertFrom-CIPolicy -XmlFilePath $AuditXml -BinaryFilePath $AuditCip


    $policyId = Get-PolicyIdFromXml $AuditXml
    $sacState = Get-SacState
    $plan = [ordered]@{
        schema = 1
        release = '0.27.8'
        policy_name = $PolicyName
        policy_id = $policyId
        source_template = $TemplatePath
        source_template_strategy = 'Microsoft SmartAppControl.xml derived audit-only policy'
        conditional_windows_lockdown_removed = $true
        jarvis_rule_level = 'Hash'
        broad_path_rules_added = $false
        sac_state_before = $sacState
        sac_known_policy_id = $KnownSacPolicyId
        runtime_tag = [string]$inventory.provenance.llama_cpp_tag
        runtime_variant = [string]$inventory.provenance.variant
        runtime_archive_sha256 = [string]$inventory.provenance.main_archive_sha256
        runtime_files = @($inventory.files)
        audit_xml = $AuditXml
        audit_cip = $AuditCip
        appcontrol_mode = 'observe_only'
        enforcement_available = $false
        generated_at = (Get-Date).ToString('o')
    }
    ($plan | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $PlanPath -Encoding UTF8
    return [pscustomobject]$plan
}

function Load-Plan {
    if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) { return (Build-PolicyArtifacts) }
    try { return (Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json) }
    catch { return (Build-PolicyArtifacts) }
}

function Probe-LlamaServer([int]$TimeoutSeconds = 20) {
    if (-not (Test-Path -LiteralPath $ServerPath -PathType Leaf)) {
        return [pscustomobject]@{ ok=$false; code=$null; text='llama-server.exe missing' }
    }
    $stem = 'jarvis_trust_probe_' + [guid]::NewGuid().ToString('N')
    $stdout = Join-Path $env:TEMP ($stem + '_out.txt')
    $stderr = Join-Path $env:TEMP ($stem + '_err.txt')
    try {
        try {
            $p = Start-Process -FilePath $ServerPath -ArgumentList @('--version') -WorkingDirectory $RuntimeDir -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
            $deadline = (Get-Date).AddSeconds([Math]::Max(3, $TimeoutSeconds))
            while (-not $p.HasExited -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 100
                $p.Refresh()
            }
            if (-not $p.HasExited) {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                return [pscustomobject]@{ ok=$false; code=$null; text=('llama-server --version timeout after ' + $TimeoutSeconds + 's') }
            }
            $text = ''
            if (Test-Path -LiteralPath $stdout) { $text += (Get-Content -LiteralPath $stdout -Raw -ErrorAction SilentlyContinue) }
            if (Test-Path -LiteralPath $stderr) { $text += (Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue) }
            return [pscustomobject]@{ ok=([int]$p.ExitCode -eq 0); code=[int]$p.ExitCode; text=$text.Trim() }
        }
        catch { return [pscustomobject]@{ ok=$false; code=$null; text=$_.Exception.Message } }
    }
    finally { Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue }
}

function Save-State([string]$Status,[object]$Plan,[object]$Extra=$null) {
    $state = [ordered]@{
        schema = 1
        status = $Status
        policy_id = [string]$Plan.policy_id
        policy_name = [string]$Plan.policy_name
        sac_state_before = [int]$Plan.sac_state_before
        current_sac_state = (Get-SacState)
        plan_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PlanPath).Hash.ToLowerInvariant()
        updated_at = (Get-Date).ToString('o')
        extra = $Extra
    }
    ($state | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $StatePath -Encoding UTF8
}

function Show-Plan([object]$Plan) {
    Write-Host ''
    Write-Host '=== JARVIS APP CONTROL TRUST PLAN ===' -ForegroundColor Cyan
    Write-Host ('Policy ID     : ' + [string]$Plan.policy_id)
    Write-Host ('Base          : Microsoft SmartAppControl.xml')
    Write-Host ('SAC atual     : ' + [string]$Plan.sac_state_before + ' (0=Off, 1=Enforce, 2=Evaluation)')
    Write-Host ('Runtime       : llama.cpp ' + [string]$Plan.runtime_tag + ' / ' + [string]$Plan.runtime_variant)
    Write-Host ('Binarios Hash : ' + @($Plan.runtime_files).Count)
    foreach ($item in @($Plan.runtime_files)) {
        Write-Host ('  ' + [string]$item.path + '  ' + [string]$item.sha256) -ForegroundColor DarkGray
    }
    Write-Host 'Regras JARVIS : Hash exato; nenhuma regra de pasta foi adicionada.' -ForegroundColor Green
    Write-Host ('Plano          : ' + $PlanPath)
}

function Set-CompatSetting([bool]$Allowed) {
    $python = Join-Path $Destination '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { return }
    $literal = if ($Allowed) { 'True' } else { 'False' }
    & $python -c "from jarvis_core.core.config import Settings; Settings.update_file_values({'local_llm_allow_ollama_compat':$literal}); print('local_llm_allow_ollama_compat=$literal')"
}

function Test-IsJarvisManagedPolicy([object]$Policy) {
    if ($null -eq $Policy) { return $false }
    if ([bool]$Policy.IsSystemPolicy) { return $false }

    $id = Normalize-Guid ([string]$Policy.PolicyID)
    $name = [string]$Policy.FriendlyName
    $legacyIds = @($LegacyJarvisPolicyIds | ForEach-Object { Normalize-Guid $_ })

    if ($legacyIds -contains $id) { return $true }
    if ($name -like 'JARVIS Smart App Control Derived*') { return $true }
    if ($name -like 'JARVIS ASUS Compatibility*') { return $true }
    if ($name -like 'JARVIS App Control Observe-Only*') { return $true }
    return $false
}

function Get-JarvisManagedPolicies {
    $policies = Get-CiPolicies
    return @($policies | Where-Object { Test-IsJarvisManagedPolicy $_ })
}

function Save-DisarmedState([string]$Status,[object[]]$Removed) {
    $state = [ordered]@{
        schema = 2
        status = $Status
        mode = 'observe_only'
        enforcement_available = $false
        removed_policy_ids = @($Removed | ForEach-Object { [string]$_.PolicyID })
        current_sac_state = (Get-SacState)
        updated_at = (Get-Date).ToString('o')
    }
    ($state | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $StatePath -Encoding UTF8
}

function Disarm-JarvisAppControl {
    Require-Administrator
    $targets = @(Get-JarvisManagedPolicies)
    if ($targets.Count -eq 0) {
        Set-CompatSetting $true
        Save-DisarmedState 'observe_only_disarmed' @()
        Write-Host 'JARVIS_APP_CONTROL: DISARMED (nenhuma policy JARVIS ativa).' -ForegroundColor Green
        return
    }

    # Supplemental policies must be removed before their base policies.
    $supplementals = @($targets | Where-Object {
        (Normalize-Guid ([string]$_.BasePolicyID)) -ne (Normalize-Guid ([string]$_.PolicyID))
    })
    $bases = @($targets | Where-Object {
        (Normalize-Guid ([string]$_.BasePolicyID)) -eq (Normalize-Guid ([string]$_.PolicyID))
    })

    $ordered = @($supplementals) + @($bases)
    foreach ($policy in $ordered) {
        $id = Normalize-Guid ([string]$policy.PolicyID)
        Write-Host ('[JARVIS/APP-CONTROL] A remover policy: ' + [string]$policy.FriendlyName + ' ' + $id) -ForegroundColor Yellow
        Invoke-CiTool -Arguments @('-rp',$id)
    }
    Invoke-CiTool -Arguments @('-r')

    $remaining = @(Get-JarvisManagedPolicies)
    if ($remaining.Count -ne 0) {
        $names = ($remaining | ForEach-Object { [string]$_.FriendlyName + ' ' + [string]$_.PolicyID }) -join '; '
        Fail ('Ainda existem policies App Control geridas pela JARVIS: ' + $names)
    }

    Set-CompatSetting $true
    Save-DisarmedState 'observe_only_disarmed' $ordered
    Write-Host 'JARVIS_APP_CONTROL: DISARMED. A JARVIS nao possui policy de bloqueio ativa.' -ForegroundColor Green
}

if ($Mode -eq 'Prepare') {
    Require-Administrator
    $nativeSetup = Join-Path $Destination 'setup_native_brain.ps1'
    if (-not (Test-Path -LiteralPath $nativeSetup -PathType Leaf)) { Fail ('setup_native_brain.ps1 em falta: ' + $nativeSetup) }
    & $nativeSetup -PrepareTrustedCudaRuntime -SkipModelDownload
    if ($LASTEXITCODE -ne 0) { Fail ('Preparacao do runtime CUDA verificado falhou (exit ' + $LASTEXITCODE + ').') }
    $plan = Build-PolicyArtifacts
    Show-Plan $plan
    Write-Host ''
    Write-Host 'PREPARE_OK: runtime CUDA verificado e plano App Control AUDIT-ONLY criado. Nenhuma policy de bloqueio foi criada.' -ForegroundColor Green
    Write-Host 'Proximo passo: .\setup_appcontrol_trust.ps1 -Mode Audit' -ForegroundColor Cyan
    exit 0
}

if ($Mode -eq 'Plan') {
    $plan = if ($RebuildPlan) { Build-PolicyArtifacts } else { Load-Plan }
    Assert-InventoryMatchesPlan $plan
    Show-Plan $plan
    Write-Host ''
    if ($RebuildPlan) {
        Write-Host 'PLAN_REBUILT: plano recriado por pedido explicito; nenhuma politica do Windows foi alterada.' -ForegroundColor Green
    }
    else {
        Write-Host 'PLAN_ONLY: plano existente reutilizado quando valido; nenhuma politica do Windows foi alterada.' -ForegroundColor Green
    }
    Write-Host 'Proximo passo opcional: .\setup_appcontrol_trust.ps1 -Mode Audit (observacao apenas)' -ForegroundColor Cyan
    exit 0
}

if ($Mode -eq 'Audit') {
    Require-Administrator
    $plan = if ($RebuildPlan) { Build-PolicyArtifacts } else { Load-Plan }
    Assert-InventoryMatchesPlan $plan
    Show-Plan $plan

    # Remove any legacy JARVIS enforcement before deploying the audit-only policy.
    $legacy = @(Get-JarvisManagedPolicies)
    if ($legacy.Count -gt 0) {
        Disarm-JarvisAppControl
    }

    Invoke-CiTool -Arguments @('-up',$AuditCip)
    Invoke-CiTool -Arguments @('-r')
    $policies = Get-CiPolicies
    $target = @($policies | Where-Object { (Normalize-Guid ([string]$_.PolicyID)) -eq (Normalize-Guid ([string]$plan.policy_id)) })
    if ($target.Count -eq 0) { Fail 'A policy Audit foi enviada mas nao aparece em CiTool -lp.' }
    $options = @($target[0].PolicyOptions | ForEach-Object { [string]$_ })
    if ($options -notcontains 'Enabled:Audit Mode') { Fail 'A policy JARVIS instalada nao esta em Audit Mode. Foi removida por seguranca.' }

    Save-State 'audit_observe_only' $plan ([ordered]@{ enforcement_available=$false })
    Write-Host ''
    Write-Host 'AUDIT_READY: JARVIS instalada apenas para observacao. Esta release nao possui caminho Enforce.' -ForegroundColor Green
    Write-Host 'Para retirar tambem a policy de auditoria: .\setup_appcontrol_trust.ps1 -Mode Disarm' -ForegroundColor Cyan
    exit 0
}

if ($Mode -eq 'Status') {
    Write-Host '=== JARVIS APP CONTROL STATUS (OBSERVE-ONLY) ===' -ForegroundColor Cyan
    Write-Host ('SAC registry state : ' + (Get-SacState) + ' (read-only; JARVIS nao altera este valor)')
    Write-Host 'Enforcement path   : DISABLED IN THIS RELEASE' -ForegroundColor Green

    $policies = Try-Get-CiPolicies
    if ($null -eq $policies) {
        Write-Host 'JARVIS policies    : UNKNOWN (CiTool requer elevacao para inventario neste Windows)' -ForegroundColor Yellow
        Write-Host '                     Reexecuta apenas -Mode Status como Administrador para confirmar.' -ForegroundColor DarkYellow
    }
    else {
        $targets = @($policies | Where-Object { Test-IsJarvisManagedPolicy $_ })
        Write-Host ('JARVIS policies    : ' + $targets.Count)
        if ($targets.Count -gt 0) {
            $targets | Format-List PolicyID,BasePolicyID,FriendlyName,VersionString,IsEnforced,IsAuthorized,IsSystemPolicy,PolicyOptions
        }
    }

    $probe = Probe-LlamaServer -TimeoutSeconds 20
    Write-Host ('llama probe        : ' + $probe.ok + ' / ' + [string]$probe.code)
    if (-not $probe.ok -and $probe.text) { Write-Host ('llama probe detail : ' + [string]$probe.text) -ForegroundColor Yellow }
    if (Test-Path -LiteralPath $StatePath) {
        Write-Host ('state              : ' + (Get-Content -LiteralPath $StatePath -Raw))
    }
    exit 0
}

if ($Mode -eq 'Disarm') {
    Disarm-JarvisAppControl
    exit 0
}

if ($Mode -eq 'Rollback') {
    # Backward-compatible alias. It no longer changes the Windows Smart App Control registry state.
    Disarm-JarvisAppControl
    Write-Host 'ROLLBACK_ALIAS: apenas policies JARVIS foram removidas; Smart App Control do Windows nao foi alterado.' -ForegroundColor Yellow
    exit 0
}
