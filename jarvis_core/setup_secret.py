from __future__ import annotations

import getpass
import sys

from jarvis_core.services.secret_store import set_secret, secret_status


TARGETS = {
    "openai": ("openai_api_key", "OpenAI API key"),
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1].lower() not in TARGETS:
        print("Uso: python -m jarvis_core.setup_secret openai")
        return 2

    key = sys.argv[1].lower()
    username, label = TARGETS[key]
    value = getpass.getpass(f"{label} (não será mostrado): ").strip()
    if not value:
        print("Nenhuma chave guardada.")
        return 1

    try:
        set_secret(username, value)
        status = secret_status(username)
    except Exception as exc:
        print(f"Falhou o acesso seguro ao gestor de credenciais: {type(exc).__name__}.")
        return 3
    if not status.get("credential_manager_set"):
        print("A credencial não pôde ser confirmada no gestor de credenciais.")
        return 4
    print(f"{label} guardada e confirmada no gestor de credenciais do Windows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
