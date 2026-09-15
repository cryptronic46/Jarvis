$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $Root
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$TempPy = Join-Path $env:TEMP ("jarvis-clean-history-" + [guid]::NewGuid().ToString() + ".py")

Write-Host "[JARVIS DATA] Cleaning known development/fuzz chat artifacts only ..."
& (Join-Path $Root "backup-encrypted-history.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Code = @'
import asyncio
import re
from jarvis_web.backend.session_store import SessionStore

EXACT = {
    "${jndi:ldap://127.0.0.1/x}",
    "<script>alert('x')</script>",
    "日本語 العربية кириллица",
    "Olá 👩🏽‍💻🚀",
}
PREFIXES = (
    "combining ",
    "texto com RTL ",
    "AUTH PENTEST ",
)

def is_test_artifact(item):
    title = item.get("title", "")
    count = int(item.get("message_count", 0))
    if title in EXACT:
        return True
    if any(title.startswith(prefix) for prefix in PREFIXES):
        return True
    if re.fullmatch(r"A{12,}.*", title):
        return True
    if title == "Nova conversa" and count == 0:
        return True
    return False

async def main():
    store = SessionStore()
    items = await store.list()
    targets = [item for item in items if is_test_artifact(item)]
    for item in targets:
        await store.delete(item["id"])
        print(f"[REMOVED] {item['title']}")
    remaining = await store.list()
    print(f"[PASS] removed={len(targets)} remaining={len(remaining)}")

asyncio.run(main())
'@

try {
    Set-Content -LiteralPath $TempPy -Value $Code -Encoding UTF8
    Push-Location $ProjectRoot
    try {
        & $Python $TempPy
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally { Pop-Location }
}
finally { Remove-Item -LiteralPath $TempPy -ErrorAction SilentlyContinue }
