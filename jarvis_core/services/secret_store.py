from __future__ import annotations

import os
from typing import Optional


SERVICE_NAME = "JARVIS"


def get_secret(username: str, env_name: str | None = None) -> Optional[str]:
    if env_name:
        value = os.getenv(env_name)
        if value:
            return value.strip()

    try:
        import keyring
        value = keyring.get_password(SERVICE_NAME, username)
        return value.strip() if value else None
    except Exception:
        return None



def secret_status(
    username: str,
    env_name: str | None = None,
) -> dict[str, object]:
    """Return secret source/status without revealing secret material."""
    environment_set = False
    if env_name:
        environment_set = bool(
            (os.getenv(env_name) or "").strip()
        )

    credential_manager_set = False
    credential_error = None
    try:
        import keyring
        credential_manager_set = bool(
            (
                keyring.get_password(
                    SERVICE_NAME,
                    username,
                )
                or ""
            ).strip()
        )
    except Exception as exc:
        credential_error = (
            f"{type(exc).__name__}: {exc}"
        )[:240]

    if environment_set:
        effective_source = "process_environment"
    elif credential_manager_set:
        effective_source = "windows_credential_manager"
    else:
        effective_source = "none"

    return {
        "configured": (
            environment_set
            or credential_manager_set
        ),
        "effective_source": effective_source,
        "process_environment_set": environment_set,
        "credential_manager_set": credential_manager_set,
        "environment_overrides_credential_manager": (
            environment_set
            and credential_manager_set
        ),
        "credential_manager_error": credential_error,
    }


def set_secret(username: str, value: str) -> None:
    import keyring

    value = value.strip()
    if not value:
        raise ValueError("Secret vazio.")
    keyring.set_password(SERVICE_NAME, username, value)


def delete_secret(username: str) -> bool:
    try:
        import keyring
        keyring.delete_password(SERVICE_NAME, username)
        return True
    except Exception:
        return False
