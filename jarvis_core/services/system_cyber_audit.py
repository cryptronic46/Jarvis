from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json
import platform
import subprocess

from jarvis_core.core.subprocess_text import decode_subprocess_stream

from jarvis_core.tools.security_audit import run_security_audit
from jarvis_core.services.security_watch import get_security_watch_status
from jarvis_core.services.cyber_knowledge import cyber_vault


HARDENING_SCRIPT = r'''
$ErrorActionPreference = "SilentlyContinue"

function Read-RegValue($Path, $Name) {
    try {
        $item = Get-ItemProperty -Path $Path -Name $Name -ErrorAction Stop
        return $item.$Name
    } catch {
        return $null
    }
}

$result = [ordered]@{
    ok = $true
    uac = [ordered]@{}
    rdp = [ordered]@{}
    smb = [ordered]@{}
    secure_boot = $null
    secure_boot_supported = $null
    bitlocker = @()
    latest_hotfix = $null
    defender_extended = [ordered]@{}
    errors = @()
}

try {
    $uacPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
    $result.uac = [ordered]@{
        enabled = (Read-RegValue $uacPath "EnableLUA")
        consent_prompt_behavior_admin = (
            Read-RegValue $uacPath "ConsentPromptBehaviorAdmin"
        )
        prompt_on_secure_desktop = (
            Read-RegValue $uacPath "PromptOnSecureDesktop"
        )
    }
} catch {
    $result.errors += "UAC: $($_.Exception.Message)"
}

try {
    $rdpPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp"
    $result.rdp = [ordered]@{
        nla_user_authentication = (
            Read-RegValue $rdpPath "UserAuthentication"
        )
        security_layer = (
            Read-RegValue $rdpPath "SecurityLayer"
        )
        min_encryption_level = (
            Read-RegValue $rdpPath "MinEncryptionLevel"
        )
    }
} catch {
    $result.errors += "RDP: $($_.Exception.Message)"
}

try {
    $smb = Get-SmbServerConfiguration
    if ($null -ne $smb) {
        $result.smb = [ordered]@{
            smb1_enabled = [bool]$smb.EnableSMB1Protocol
            smb2_enabled = [bool]$smb.EnableSMB2Protocol
            encrypt_data = [bool]$smb.EncryptData
            reject_unencrypted_access = [bool]$smb.RejectUnencryptedAccess
        }
    }
} catch {
    $result.errors += "SMB: $($_.Exception.Message)"
}

try {
    $sb = Confirm-SecureBootUEFI
    $result.secure_boot = [bool]$sb
    $result.secure_boot_supported = $true
} catch {
    $result.secure_boot_supported = $false
    $result.errors += "SecureBoot: $($_.Exception.Message)"
}

try {
    $result.bitlocker = @(
        Get-BitLockerVolume |
        ForEach-Object {
            [PSCustomObject]@{
                mount_point = $_.MountPoint
                volume_type = [string]$_.VolumeType
                volume_status = [string]$_.VolumeStatus
                protection_status = [string]$_.ProtectionStatus
                encryption_percentage = [double]$_.EncryptionPercentage
                encryption_method = [string]$_.EncryptionMethod
            }
        }
    )
} catch {
    $result.errors += "BitLocker: $($_.Exception.Message)"
}

try {
    $hotfix = Get-HotFix |
        Where-Object { $null -ne $_.InstalledOn } |
        Sort-Object InstalledOn -Descending |
        Select-Object -First 1
    if ($null -ne $hotfix) {
        $result.latest_hotfix = [ordered]@{
            hotfix_id = $hotfix.HotFixID
            description = $hotfix.Description
            installed_on = $hotfix.InstalledOn.ToString("o")
        }
    }
} catch {
    $result.errors += "HotFix: $($_.Exception.Message)"
}

try {
    $mp = Get-MpComputerStatus
    if ($null -ne $mp) {
        $result.defender_extended = [ordered]@{
            tamper_protected = (
                if ($null -ne $mp.IsTamperProtected) {
                    [bool]$mp.IsTamperProtected
                } else { $null }
            )
            antivirus_signature_age_days = (
                if ($null -ne $mp.AntivirusSignatureAge) {
                    [int]$mp.AntivirusSignatureAge
                } else { $null }
            )
            quick_scan_age_days = (
                if ($null -ne $mp.QuickScanAge) {
                    [int]$mp.QuickScanAge
                } else { $null }
            )
            full_scan_age_days = (
                if ($null -ne $mp.FullScanAge) {
                    [int]$mp.FullScanAge
                } else { $null }
            )
        }
    }
} catch {
    $result.errors += "DefenderExtended: $($_.Exception.Message)"
}

$result | ConvertTo-Json -Depth 8 -Compress
'''


SEVERITY_WEIGHT = {
    "critical": 40,
    "high": 20,
    "attention": 10,
    "moderate": 7,
    "info": 0,
    "good": 0,
    "unknown": 0,
}


def _windows() -> bool:
    return platform.system().lower() == "windows"


def _powershell_hardening() -> dict[str, Any]:
    if not _windows():
        return {
            "ok": False,
            "error": "WINDOWS_ONLY",
            "message": "A análise de hardening requer Windows.",
        }

    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                HARDENING_SCRIPT,
            ],
            capture_output=True,
            timeout=18,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return {"ok": False, "error": "POWERSHELL_NOT_FOUND"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "POWERSHELL_TIMEOUT"}
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    raw = decode_subprocess_stream(completed.stdout).strip()
    if not raw:
        return {
            "ok": False,
            "error": "POWERSHELL_EMPTY_OUTPUT",
            "message": decode_subprocess_stream(completed.stderr).strip(),
        }

    try:
        value = json.loads(raw.splitlines()[-1])
        return value if isinstance(value, dict) else {
            "ok": False,
            "error": "INVALID_HARDENING_RESULT",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "POWERSHELL_INVALID_JSON",
            "message": f"{type(exc).__name__}: {exc}",
        }


def _finding(
    code: str,
    title: str,
    severity: str,
    evidence: str,
    interpretation: str,
    recommendation: str,
    knowledge_query: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "severity": severity,
        "evidence": evidence,
        "interpretation": interpretation,
        "recommendation": recommendation,
        "knowledge_query": knowledge_query,
        "evidence_class": "observed",
    }


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _core_findings(
    audit: dict[str, Any],
    watch: dict[str, Any],
    hardening: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    posture = audit.get("windows_security") or {}
    accounts = audit.get("accounts") or {}
    sessions = audit.get("sessions") or {}
    network = audit.get("network") or {}
    defender = posture.get("defender") or {}

    others = accounts.get(
        "other_enabled_or_unknown_admin_principals",
        [],
    ) or []

    if accounts.get("only_current_enabled_admin_detected") is True:
        findings.append(_finding(
            "ADMIN_ONLY_CURRENT",
            "Privilégios administrativos",
            "good",
            "O utilizador atual é o único administrador habilitado que foi confirmado.",
            "Reduz o número de identidades com capacidade de alterar controlos de segurança.",
            "Manter o princípio do menor privilégio e rever alterações ao grupo Administradores.",
            "least privilege privileged accounts UAC administrators",
        ))
    elif others:
        findings.append(_finding(
            "OTHER_ADMIN",
            "Outros administradores",
            "attention",
            f"Foram encontrados {len(others)} outro(s) principal(is) administrador(es) habilitado(s) ou de estado indeterminado.",
            "Mais identidades privilegiadas aumentam a superfície de abuso de credenciais e elevação.",
            "Confirmar se cada administrador adicional é esperado e remover privilégios desnecessários.",
            "least privilege privileged accounts administrators",
        ))
    else:
        findings.append(_finding(
            "ADMIN_STATE_UNKNOWN",
            "Privilégios administrativos",
            "unknown",
            "Não foi possível confirmar de forma conclusiva se existem outros administradores habilitados.",
            "A ausência de confirmação não deve ser tratada como ausência de risco.",
            "Repetir a auditoria com acesso suficiente para enumerar os administradores locais.",
            "least privilege privileged accounts administrators",
        ))

    remote_sessions = sessions.get("remote_sessions") or []
    smb_sessions = posture.get("smb_sessions") or []

    if remote_sessions:
        findings.append(_finding(
            "REMOTE_SESSION_ACTIVE",
            "Sessão remota interativa",
            "high",
            f"Existem {len(remote_sessions)} sessão(ões) remota(s) interativa(s) ativas.",
            "Uma sessão remota real é evidência de acesso remoto, mas pode ser legítima.",
            "Identificar imediatamente o utilizador e cliente remoto e confirmar se a sessão é autorizada.",
            "Remote Desktop RDP remote services valid accounts",
        ))
    else:
        findings.append(_finding(
            "NO_REMOTE_SESSION",
            "Sessões remotas",
            "good",
            "Não foi detetada uma sessão RDP/interativa remota ativa.",
            "Não há evidência deste tipo de acesso remoto no instante da recolha.",
            "Manter monitorização; este controlo é pontual e não prova que nunca ocorreu acesso remoto.",
            "Remote Desktop RDP remote services",
        ))

    if smb_sessions:
        findings.append(_finding(
            "SMB_SESSION_ACTIVE",
            "Sessões SMB",
            "attention",
            f"Existem {len(smb_sessions)} sessão(ões) SMB ativa(s).",
            "SMB pode ser legítimo, mas também é relevante para movimento lateral e acesso a ficheiros.",
            "Confirmar os clientes e utilizadores das sessões SMB e validar se são esperados.",
            "SMB Windows lateral movement network shares",
        ))

    remote_tools = network.get("remote_access_software_running") or []
    if remote_tools:
        products = sorted({
            str(row.get("product"))
            for row in remote_tools
            if row.get("product")
        })
        findings.append(_finding(
            "REMOTE_ACCESS_SOFTWARE",
            "Software de acesso remoto",
            "attention",
            "Em execução: " + ", ".join(products) + ".",
            "Software remoto instalado ou ativo não significa compromisso, mas cria uma via de administração que deve ser conhecida.",
            "Confirmar que cada produto é teu, está atualizado e protegido por autenticação forte.",
            "remote access software remote services valid accounts",
        ))

    firewalls = posture.get("firewall") or []
    firewall_all = bool(
        firewalls
        and all(row.get("enabled") is True for row in firewalls)
    )
    if firewall_all:
        findings.append(_finding(
            "FIREWALL_ENABLED",
            "Windows Firewall",
            "good",
            "Todos os perfis de Firewall enumerados estão ativos.",
            "A firewall reduz exposição ao aplicar regras ao tráfego de rede.",
            "Manter ativa e rever regras de entrada quando instalar serviços novos.",
            "Windows Firewall network protection security controls",
        ))
    else:
        disabled = [
            str(row.get("name"))
            for row in firewalls
            if row.get("enabled") is False
        ]
        findings.append(_finding(
            "FIREWALL_NOT_FULLY_ENABLED",
            "Windows Firewall",
            "high",
            (
                "Perfis desativados: " + ", ".join(disabled) + "."
                if disabled else
                "Não foi possível confirmar a Firewall ativa em todos os perfis."
            ),
            "Um perfil desativado pode aumentar a exposição de serviços acessíveis pela rede.",
            "Ativar os perfis necessários depois de confirmar que não existe uma configuração deliberada que dependa disso.",
            "Windows Firewall network protection security controls",
        ))

    rt = defender.get("real_time_protection_enabled")
    if rt is True:
        findings.append(_finding(
            "DEFENDER_REALTIME_ENABLED",
            "Microsoft Defender",
            "good",
            "A proteção em tempo real está ativa.",
            "Existe monitorização antimalware em tempo real.",
            "Manter o Defender atualizado e não assumir que antimalware substitui hardening e patching.",
            "Microsoft Defender real time protection malware",
        ))
    elif rt is False:
        findings.append(_finding(
            "DEFENDER_REALTIME_DISABLED",
            "Microsoft Defender",
            "high",
            "A proteção em tempo real aparece desativada.",
            "Reduz uma camada importante de deteção e prevenção de malware.",
            "Confirmar a causa e reativar a proteção, salvo se existir outro produto de segurança que o justifique.",
            "Microsoft Defender real time protection malware",
        ))
    else:
        findings.append(_finding(
            "DEFENDER_UNKNOWN",
            "Microsoft Defender",
            "unknown",
            "O estado da proteção em tempo real não foi confirmado.",
            "Não é seguro assumir proteção ativa sem evidência.",
            "Repetir a consulta do Defender e validar o produto antimalware ativo.",
            "Microsoft Defender real time protection malware",
        ))

    rdp = posture.get("rdp_enabled")
    if rdp is True:
        nla = (hardening.get("rdp") or {}).get("nla_user_authentication")
        severity = "attention"
        evidence = "RDP está ativado."
        if nla == 1:
            evidence += " Network Level Authentication aparece ativa."
        elif nla == 0:
            severity = "high"
            evidence += " Network Level Authentication aparece desativada."

        findings.append(_finding(
            "RDP_ENABLED",
            "Remote Desktop",
            severity,
            evidence,
            "RDP aumenta a superfície de acesso remoto; NLA reduz parte do risco quando o serviço é necessário.",
            "Se não usas RDP, mantê-lo desativado. Se usas, restringir por firewall/VPN e usar NLA e autenticação forte.",
            "Remote Desktop RDP network level authentication remote services",
        ))
    elif rdp is False:
        findings.append(_finding(
            "RDP_DISABLED",
            "Remote Desktop",
            "good",
            "RDP está desativado.",
            "Um serviço remoto desnecessário desligado reduz a superfície de ataque.",
            "Manter desativado enquanto não for necessário.",
            "Remote Desktop RDP remote services",
        ))

    if posture.get("remote_assistance_enabled") is True:
        findings.append(_finding(
            "REMOTE_ASSISTANCE_ENABLED",
            "Assistência Remota",
            "attention",
            "A Assistência Remota do Windows está permitida.",
            "Não significa que alguém esteja ligado, mas mantém uma funcionalidade de assistência remota disponível.",
            "Desativar se não utilizas esta funcionalidade; caso a uses, validar sempre a origem dos pedidos.",
            "Windows Remote Assistance remote services",
        ))

    uac = hardening.get("uac") or {}
    enable_lua = uac.get("enabled")
    if enable_lua == 1:
        findings.append(_finding(
            "UAC_ENABLED",
            "User Account Control",
            "good",
            "EnableLUA=1; UAC aparece ativado.",
            "UAC introduz uma fronteira de elevação para operações administrativas.",
            "Manter UAC ativo e evitar aprovar elevações que não reconheças.",
            "UAC least privilege privilege escalation Windows",
        ))
    elif enable_lua == 0:
        findings.append(_finding(
            "UAC_DISABLED",
            "User Account Control",
            "high",
            "EnableLUA=0; UAC aparece desativado.",
            "Desativar UAC reduz uma barreira importante entre sessão normal e ações administrativas.",
            "Reativar UAC após validar compatibilidade com aplicações legadas.",
            "UAC least privilege privilege escalation Windows",
        ))

    smb = hardening.get("smb") or {}
    if smb.get("smb1_enabled") is True:
        findings.append(_finding(
            "SMB1_ENABLED",
            "SMB1",
            "high",
            "O servidor SMB reporta SMB1 ativado.",
            "SMB1 é um protocolo legado com superfície de ataque desnecessária em redes modernas.",
            "Desativar SMB1 se nenhum equipamento legado depender dele e validar funcionamento após a alteração.",
            "SMB1 Windows lateral movement legacy protocol",
        ))
    elif smb.get("smb1_enabled") is False:
        findings.append(_finding(
            "SMB1_DISABLED",
            "SMB1",
            "good",
            "SMB1 aparece desativado.",
            "Remove uma superfície de protocolo legado.",
            "Manter desativado salvo necessidade explícita e controlada.",
            "SMB1 Windows lateral movement legacy protocol",
        ))

    if hardening.get("secure_boot_supported") is True:
        if hardening.get("secure_boot") is True:
            findings.append(_finding(
                "SECURE_BOOT_ENABLED",
                "Secure Boot",
                "good",
                "Secure Boot está ativo.",
                "Ajuda a proteger a cadeia de arranque contra componentes não confiáveis.",
                "Manter ativo e usar firmware/bootloaders assinados.",
                "Secure Boot Windows boot security",
            ))
        elif hardening.get("secure_boot") is False:
            findings.append(_finding(
                "SECURE_BOOT_DISABLED",
                "Secure Boot",
                "attention",
                "Secure Boot é suportado mas aparece desativado.",
                "A cadeia de arranque perde uma proteção contra bootloaders/componentes não confiáveis.",
                "Avaliar ativação na UEFI depois de confirmar compatibilidade do sistema.",
                "Secure Boot Windows boot security",
            ))

    bitlocker = hardening.get("bitlocker") or []
    os_volumes = [
        row for row in bitlocker
        if str(row.get("volume_type") or "").lower() == "operatingsystem"
        or str(row.get("mount_point") or "").upper().startswith("C:")
    ]
    if os_volumes:
        protected = any(
            str(row.get("protection_status") or "").lower() in {"on", "1"}
            for row in os_volumes
        )
        findings.append(_finding(
            "BITLOCKER_OS_PROTECTED"
            if protected
            else "BITLOCKER_OS_UNPROTECTED",
            "Encriptação do disco do sistema",
            "good" if protected else "attention",
            (
                "O volume do sistema reporta proteção BitLocker/Device Encryption ativa."
                if protected else
                "O volume do sistema não reporta proteção BitLocker ativa."
            ),
            "Encriptação de disco protege dados em repouso se o equipamento for perdido ou o disco for removido.",
            (
                "Manter a proteção e guardar a chave de recuperação de forma segura."
                if protected else
                "Avaliar BitLocker/Device Encryption, sobretudo para proteção física dos dados."
            ),
            "BitLocker data protection Windows encryption",
        ))

    ext = hardening.get("defender_extended") or {}
    sig_age = ext.get("antivirus_signature_age_days")
    if isinstance(sig_age, int):
        if sig_age > 7:
            findings.append(_finding(
                "DEFENDER_SIGNATURE_OLD",
                "Assinaturas do Defender",
                "attention",
                f"A idade reportada das assinaturas é {sig_age} dias.",
                "Assinaturas antigas podem reduzir a capacidade de reconhecer ameaças conhecidas.",
                "Atualizar as definições do Defender e confirmar a data após a atualização.",
                "Microsoft Defender security intelligence updates signatures",
            ))
        else:
            findings.append(_finding(
                "DEFENDER_SIGNATURE_FRESH",
                "Assinaturas do Defender",
                "good",
                f"As assinaturas têm aproximadamente {sig_age} dia(s).",
                "A inteligência antimalware está recente segundo o estado reportado.",
                "Manter as atualizações automáticas.",
                "Microsoft Defender security intelligence updates signatures",
            ))

    hotfix = hardening.get("latest_hotfix") or {}
    installed = _parse_iso(hotfix.get("installed_on"))
    if installed:
        age = (datetime.now(installed.tzinfo) - installed).days
        if age > 60:
            findings.append(_finding(
                "HOTFIX_OLD",
                "Atualizações do Windows",
                "attention",
                f"O hotfix mais recente enumerado é {hotfix.get('hotfix_id')} e tem cerca de {age} dias.",
                "Isto sugere que vale a pena verificar o Windows Update, mas Get-HotFix não representa todos os mecanismos de atualização.",
                "Abrir o Windows Update e confirmar atualizações cumulativas e de segurança pendentes.",
                "Windows security updates patch management vulnerability management",
            ))
        else:
            findings.append(_finding(
                "HOTFIX_RECENT",
                "Atualizações do Windows",
                "good",
                f"O hotfix mais recente enumerado é {hotfix.get('hotfix_id')} com cerca de {age} dias.",
                "Existe evidência recente de atualização, embora isto não prove que todos os patches estejam instalados.",
                "Continuar a verificar o Windows Update regularmente.",
                "Windows security updates patch management vulnerability management",
            ))

    counts = network.get("counts") or {}
    listener_count = int(counts.get("listeners_non_loopback") or 0)
    if listener_count:
        listeners = (
            (network.get("filtered") or {}).get(
                "non_loopback_listeners",
                [],
            )
            or []
        )
        labels = []
        for row in listeners[:8]:
            local = row.get("local") or {}
            proc = row.get("process") or "processo desconhecido"
            labels.append(f"{proc}:{local.get('port','?')}")

        findings.append(_finding(
            "NETWORK_LISTENERS",
            "Serviços em escuta na rede",
            "info",
            (
                f"Existem {listener_count} listener(s) não-loopback. "
                + (
                    "Exemplos: " + ", ".join(labels) + "."
                    if labels else ""
                )
            ),
            "Um listener apenas indica que um processo aceita ligações; não prova exposição à Internet nem vulnerabilidade.",
            "Rever listeners desconhecidos e confirmar processo, regra de firewall e necessidade do serviço.",
            "network services listening ports firewall attack surface",
        ))

    public_count = int(counts.get("public_established") or 0)
    if public_count:
        findings.append(_finding(
            "PUBLIC_CONNECTIONS",
            "Ligações públicas estabelecidas",
            "info",
            f"Existem {public_count} ligação(ões) públicas estabelecidas no instante da recolha.",
            "Tráfego Internet normal de browsers, launchers e serviços cloud gera ligações públicas; isto não é evidência de intrusão.",
            "Investigar apenas ligações associadas a processos, destinos ou comportamento que não reconheças.",
            "network connections established processes incident investigation",
        ))

    for alert in watch.get("alerts") or []:
        sev = str(alert.get("severity") or "info").lower()
        mapped = (
            "critical"
            if sev == "critical"
            else "attention"
            if sev == "attention"
            else "info"
        )
        findings.append(_finding(
            f"WATCH_{alert.get('code') or 'CHANGE'}",
            "Alteração face à baseline",
            mapped,
            str(
                alert.get("message")
                or "Alteração de segurança detetada."
            ),
            "Uma alteração face a uma baseline conhecida merece validação porque representa desvio do estado habitual.",
            "Confirmar se a alteração foi provocada por ti; se não, preservar evidência antes de modificar o sistema.",
            "security baseline change detection incident response",
        ))

    return findings


def _risk(findings: list[dict[str, Any]]) -> dict[str, Any]:
    score = sum(
        SEVERITY_WEIGHT.get(
            str(row.get("severity") or "").lower(),
            0,
        )
        for row in findings
    )
    critical = sum(
        1 for row in findings
        if row.get("severity") == "critical"
    )
    high = sum(
        1 for row in findings
        if row.get("severity") == "high"
    )
    attention = sum(
        1 for row in findings
        if row.get("severity") in {"attention", "moderate"}
    )

    if critical:
        level = "critical"
    elif score >= 35 or high >= 2:
        level = "high"
    elif score >= 10:
        level = "moderate"
    else:
        level = "low"

    return {
        "level": level,
        "score": score,
        "critical_findings": critical,
        "high_findings": high,
        "attention_findings": attention,
    }


def _knowledge_for_findings(
    findings: list[dict[str, Any]],
    limit_queries: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    vault = cyber_vault()
    refs: list[dict[str, Any]] = []
    by_code: dict[str, list[str]] = {}
    seen_ref = set()
    seen_query = set()

    priority = {
        "critical": 0,
        "high": 1,
        "attention": 2,
        "moderate": 2,
        "info": 3,
        "good": 4,
        "unknown": 5,
    }

    ordered = sorted(
        findings,
        key=lambda row: priority.get(row.get("severity"), 9),
    )

    for finding in ordered:
        query = str(
            finding.get("knowledge_query") or ""
        ).strip()
        if not query or query in seen_query:
            continue
        if len(seen_query) >= limit_queries:
            break
        seen_query.add(query)

        result = vault.search(query, limit=3)
        ids = []
        for row in result.get("results") or []:
            key = (
                row.get("source_id"),
                row.get("external_id"),
                row.get("title"),
            )
            ref_id = (
                f"{row.get('publisher') or row.get('source_id')}:"
                f"{row.get('external_id') or row.get('id')}"
            )
            ids.append(ref_id)

            if key in seen_ref:
                continue
            seen_ref.add(key)
            refs.append({
                "ref_id": ref_id,
                "title": row.get("title"),
                "publisher": row.get("publisher"),
                "source_id": row.get("source_id"),
                "external_id": row.get("external_id"),
                "trust": row.get("trust"),
                "provenance": row.get("provenance"),
                "url": row.get("url"),
                "snippet": row.get("snippet"),
            })

        if ids:
            by_code[finding["code"]] = ids[:3]

    return refs[:24], by_code


def analyze_system_cybersecurity(
    detail: str = "standard",
) -> dict[str, Any]:
    detail = str(detail or "standard").lower().strip()
    if detail not in {"standard", "full", "raw"}:
        detail = "standard"

    audit = run_security_audit()
    watch = get_security_watch_status()
    hardening = _powershell_hardening()

    if not audit.get("ok"):
        return {
            "ok": False,
            "error": "BASE_SECURITY_AUDIT_FAILED",
            "base_audit": audit,
        }

    findings = _core_findings(
        audit,
        watch,
        hardening,
    )
    risk = _risk(findings)
    references, refs_by_code = _knowledge_for_findings(findings)

    for finding in findings:
        finding["knowledge_refs"] = refs_by_code.get(
            finding["code"],
            [],
        )

    collector_states = {
        "base_security_audit": bool(audit.get("ok")),
        "security_watch": bool(watch.get("ok")),
        "windows_hardening": bool(hardening.get("ok")),
        "knowledge_vault": True,
    }
    confidence = (
        "high"
        if all(collector_states.values())
        else "medium"
        if collector_states["base_security_audit"]
        else "low"
    )

    actionable = [
        row for row in findings
        if row.get("severity")
        in {"critical", "high", "attention", "moderate"}
    ]
    actionable.sort(
        key=lambda row: {
            "critical": 0,
            "high": 1,
            "attention": 2,
            "moderate": 3,
        }.get(row.get("severity"), 9)
    )

    summary = audit.get("summary") or {}
    compromise_evidence = bool(
        (audit.get("sessions") or {}).get("remote_sessions")
        or (audit.get("windows_security") or {}).get("smb_sessions")
        or any(
            row.get("severity") == "critical"
            for row in watch.get("alerts") or []
        )
    )

    conclusion = (
        "Existem indicadores que exigem validação imediata."
        if compromise_evidence
        else
        "Não encontrei evidência direta de compromisso nos controlos verificados. "
        "Isto não equivale a provar ausência de malware ou intrusão."
    )

    result = {
        "ok": True,
        "sampled_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "mode": detail,
        "risk": risk,
        "confidence": confidence,
        "collector_states": collector_states,
        "summary": {
            "current_user": summary.get("current_user"),
            "current_user_admin": summary.get("current_user_admin"),
            "only_current_enabled_admin_detected": summary.get(
                "only_current_enabled_admin_detected"
            ),
            "remote_interactive_sessions": summary.get(
                "remote_interactive_session_count",
                0,
            ),
            "smb_sessions": summary.get("smb_session_count", 0),
            "remote_access_software": summary.get(
                "remote_access_software_count",
                0,
            ),
            "firewall_all_enabled": summary.get(
                "firewall_all_enabled"
            ),
            "defender_realtime_enabled": summary.get(
                "defender_realtime_enabled"
            ),
            "rdp_enabled": summary.get("rdp_enabled"),
            "lan_devices": (
                (summary.get("network") or {}).get(
                    "lan_device_count",
                    0,
                )
            ),
            "network_listeners": (
                (summary.get("network") or {}).get(
                    "non_loopback_listener_count",
                    0,
                )
            ),
            "public_connections": (
                (summary.get("network") or {}).get(
                    "public_connection_count",
                    0,
                )
            ),
        },
        "findings": findings,
        "priorities": actionable[:8],
        "knowledge_references": references,
        "conclusion": conclusion,
        "limitations": [
            "É uma fotografia do estado atual; atividade passada pode não estar presente agora.",
            "Uma porta LISTEN ou uma ligação pública não é, por si só, evidência de intrusão.",
            "A descoberta da LAN é passiva e depende da tabela de vizinhos do Windows.",
            "Esta versão não faz correspondência exata de CVEs por produto/build/patch instalado; a CISA KEV é usada como conhecimento, não como prova de vulnerabilidade local.",
            "Não é feita análise de memória, rootkits, firmware ou forense profunda nesta auditoria.",
            "Controlos que o Windows não permita consultar ficam como desconhecidos em vez de serem assumidos como seguros.",
        ],
        "read_only": True,
    }

    if detail == "full":
        result["hardening"] = hardening
        result["base_audit_summary"] = audit.get("summary")
        result["network_context"] = {
            "listeners": (
                (audit.get("network") or {}).get(
                    "filtered",
                    {},
                ).get(
                    "non_loopback_listeners",
                    [],
                )
            )[:20],
            "remote_connections": (
                (audit.get("network") or {}).get(
                    "filtered",
                    {},
                ).get(
                    "remote_connections",
                    [],
                )
            )[:20],
            "active_lan_devices": (
                (audit.get("network") or {}).get(
                    "filtered",
                    {},
                ).get(
                    "active_lan_devices",
                    [],
                )
            )[:20],
        }
    elif detail == "raw":
        result["hardening"] = hardening
        result["base_audit"] = audit
        result["security_watch"] = watch

    return result


def _severity_label(value: str) -> str:
    return {
        "critical": "CRÍTICO",
        "high": "ALTO",
        "attention": "ATENÇÃO",
        "moderate": "MODERADO",
        "info": "INFO",
        "good": "OK",
        "unknown": "DESCONHECIDO",
    }.get(str(value or "").lower(), str(value or "").upper())


def format_system_cyber_audit(
    data: dict[str, Any],
    *,
    full: bool = False,
) -> str:
    if not data.get("ok"):
        return (
            data.get("message")
            or "Não consegui concluir a análise de cibersegurança."
        )

    risk = data.get("risk") or {}
    summary = data.get("summary") or {}
    priorities = data.get("priorities") or []
    findings = data.get("findings") or []
    refs = data.get("knowledge_references") or []

    risk_label = {
        "low": "BAIXO",
        "moderate": "MODERADO",
        "high": "ALTO",
        "critical": "CRÍTICO",
    }.get(risk.get("level"), "DESCONHECIDO")

    lines = [
        "JARVIS — ANÁLISE DE CIBERSEGURANÇA",
        (
            f"Risco global: {risk_label} · "
            f"Confiança: {str(data.get('confidence') or 'unknown').upper()}"
        ),
        "",
        "ESTADO ESSENCIAL",
        (
            "Administrador único confirmado: "
            + (
                "Sim"
                if summary.get(
                    "only_current_enabled_admin_detected"
                ) is True
                else "Não/indeterminado"
            )
        ),
        (
            f"Sessões RDP remotas: "
            f"{summary.get('remote_interactive_sessions',0)}"
        ),
        f"Sessões SMB: {summary.get('smb_sessions',0)}",
        (
            "Firewall: "
            + (
                "OK"
                if summary.get("firewall_all_enabled") is True
                else "ATENÇÃO"
            )
        ),
        (
            "Defender: "
            + (
                "Tempo real ativo"
                if summary.get(
                    "defender_realtime_enabled"
                ) is True
                else "ATENÇÃO/Não confirmado"
            )
        ),
        (
            "RDP: "
            + (
                "Ativo"
                if summary.get("rdp_enabled") is True
                else "Desativado"
                if summary.get("rdp_enabled") is False
                else "Não confirmado"
            )
        ),
        (
            f"Rede: {summary.get('lan_devices',0)} dispositivo(s) LAN · "
            f"{summary.get('network_listeners',0)} listener(s) · "
            f"{summary.get('public_connections',0)} ligação(ões) públicas"
        ),
    ]

    lines += ["", "PRIORIDADES"]
    if priorities:
        for i, row in enumerate(priorities[:8], start=1):
            lines.append(
                f"{i}. {_severity_label(row.get('severity'))} · "
                f"{row.get('title')}"
            )
            lines.append(
                f"   Evidência: {row.get('evidence')}"
            )
            lines.append(
                f"   Ação: {row.get('recommendation')}"
            )
    else:
        lines.append(
            "Nenhuma ação prioritária nos controlos verificados."
        )

    if full:
        good = [
            row for row in findings
            if row.get("severity") == "good"
        ]
        info = [
            row for row in findings
            if row.get("severity") in {"info", "unknown"}
        ]

        lines += ["", "CONTROLOS POSITIVOS"]
        for row in good[:10]:
            lines.append(
                f"- OK · {row.get('title')}: "
                f"{row.get('evidence')}"
            )

        if info:
            lines += [
                "",
                "CONTEXTO / NÃO CONFUNDIR COM INTRUSÃO",
            ]
            for row in info[:8]:
                lines.append(
                    f"- {_severity_label(row.get('severity'))} · "
                    f"{row.get('title')}: {row.get('evidence')}"
                )
                lines.append(
                    f"  Interpretação: {row.get('interpretation')}"
                )

    if refs:
        lines += ["", "CONHECIMENTO CORRELACIONADO"]
        for row in refs[:8]:
            source = (
                row.get("publisher")
                or row.get("source_id")
                or "Fonte"
            )
            external = row.get("external_id")
            suffix = (
                f" · {external}"
                if external and external != "root"
                else ""
            )
            lines.append(
                f"- {source}{suffix}: {row.get('title')}"
            )

    lines += [
        "",
        "CONCLUSÃO",
        str(data.get("conclusion") or ""),
    ]

    if full:
        lines += ["", "LIMITAÇÕES"]
        for item in data.get("limitations") or []:
            lines.append(f"- {item}")

    lines.append(
        "Detalhe: /cyber analyze system full · "
        "JSON técnico: /cyber analyze system raw"
    )
    return "\n".join(lines)
