from pathlib import Path
import os
import sys


def _configure_utf8_console() -> None:
    """Keep Portuguese text stable across Windows terminal, logs and pipes."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleCP(65001)
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass


_configure_utf8_console()

# Make every relative runtime path follow the installation itself (for example
# G:\\JARVIS) even when jarvis.py is launched from a shortcut or another cwd.
CORE_ROOT = Path(__file__).resolve().parent
os.chdir(CORE_ROOT)

from jarvis_core.services.windows_block_audit import (
    startup_preflight,
    format_startup_preflight,
)


if __name__ == "__main__":
    block_audit = startup_preflight()
    summary = format_startup_preflight(block_audit)
    if summary:
        print(summary)

    try:
        from jarvis_core.cli import main
    except Exception:
        print(
            "[PREFLIGHT] O Core falhou durante os imports depois do Windows Block Audit."
        )
        if (
            block_audit.get("motw_current")
            or block_audit.get("confirmed_block_events")
            or block_audit.get("integrity_events")
        ):
            print(
                "[PREFLIGHT] Existem sinais de bloqueio/integridade em ficheiros do JARVIS. "
                "Reve o relatorio em memory\\windows_block_audit.json."
            )
        raise

    main()
