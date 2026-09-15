from __future__ import annotations

import base64
import csv
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
from typing import Protocol


class StorageProtectionError(RuntimeError):
    pass


class DataProtector(Protocol):
    name: str

    def protect(self, plaintext: bytes) -> bytes:
        ...

    def unprotect(self, ciphertext: bytes) -> bytes:
        ...


class DirectoryAclHardener(Protocol):
    name: str

    def harden(self, path: Path) -> None:
        ...


class TestOnlyProtector:
    """Reversible test helper. NEVER a production security mechanism."""

    name = "test-only"

    def protect(self, plaintext: bytes) -> bytes:
        return b"JARVIS-TEST-ONLY-V1\n" + base64.b64encode(plaintext)

    def unprotect(self, ciphertext: bytes) -> bytes:
        prefix = b"JARVIS-TEST-ONLY-V1\n"
        if not ciphertext.startswith(prefix):
            raise StorageProtectionError("Invalid test storage envelope")
        try:
            return base64.b64decode(ciphertext[len(prefix):], validate=True)
        except Exception as exc:
            raise StorageProtectionError("Corrupt test storage envelope") from exc


class NoOpAclHardener:
    name = "test-only-noop"

    def harden(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)


class WindowsDpapiProtector:
    """Windows DPAPI using the CURRENT USER scope.

    No CRYPTPROTECT_LOCAL_MACHINE flag is used. The encrypted history is bound
    to the Windows user profile that created it, plus JARVIS-specific optional
    entropy.
    """

    name = "windows-dpapi-current-user"
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1
    _ENTROPY = b"JARVIS-Web-History-v1"

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    def __init__(self) -> None:
        if os.name != "nt":
            raise StorageProtectionError("Windows DPAPI is available only on Windows")

        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(self._DATA_BLOB),
            wintypes.LPCWSTR,
            ctypes.POINTER(self._DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(self._DATA_BLOB),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL

        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(self._DATA_BLOB),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(self._DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(self._DATA_BLOB),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL

        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    @classmethod
    def _input_blob(cls, data: bytes):
        if not data:
            # DPAPI supports empty data, but keep a stable non-null buffer.
            buffer = ctypes.create_string_buffer(b"\x00")
            blob = cls._DATA_BLOB(
                0,
                ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
            )
            return blob, buffer

        buffer = ctypes.create_string_buffer(data, len(data))
        blob = cls._DATA_BLOB(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        return blob, buffer

    def _last_error(self, operation: str) -> StorageProtectionError:
        code = ctypes.get_last_error()
        return StorageProtectionError(f"{operation} failed with Windows error {code}")

    def protect(self, plaintext: bytes) -> bytes:
        in_blob, in_buffer = self._input_blob(plaintext)
        entropy_blob, entropy_buffer = self._input_blob(self._ENTROPY)
        out_blob = self._DATA_BLOB()

        ok = self._crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "JARVIS Web encrypted conversation history",
            ctypes.byref(entropy_blob),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        # Keep Python references alive for the entire call.
        _ = (in_buffer, entropy_buffer)

        if not ok:
            raise self._last_error("CryptProtectData")

        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            if out_blob.pbData:
                self._kernel32.LocalFree(out_blob.pbData)

    def unprotect(self, ciphertext: bytes) -> bytes:
        in_blob, in_buffer = self._input_blob(ciphertext)
        entropy_blob, entropy_buffer = self._input_blob(self._ENTROPY)
        out_blob = self._DATA_BLOB()

        ok = self._crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        _ = (in_buffer, entropy_buffer)

        if not ok:
            raise self._last_error("CryptUnprotectData")

        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            if out_blob.pbData:
                self._kernel32.LocalFree(out_blob.pbData)


class WindowsAclHardener:
    """Restrict a private directory to current Windows user + LOCAL SYSTEM."""

    name = "windows-acl-current-user-system"

    _SYSTEM_SID = "S-1-5-18"
    _BROAD_SIDS = (
        "S-1-1-0",       # Everyone
        "S-1-5-11",      # Authenticated Users
        "S-1-5-32-545",  # BUILTIN\Users
    )

    def __init__(self) -> None:
        if os.name != "nt":
            raise StorageProtectionError("Windows ACL hardening requires Windows")

    @staticmethod
    def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                check=check,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = ""
            if isinstance(exc, subprocess.CalledProcessError):
                detail = (exc.stderr or exc.stdout or "").strip()
            raise StorageProtectionError(
                f"Windows ACL command failed: {' '.join(args)}"
                + (f" — {detail}" if detail else "")
            ) from exc

    @classmethod
    def _current_user_sid(cls) -> str:
        result = cls._run(["whoami", "/user", "/fo", "csv", "/nh"])
        try:
            row = next(csv.reader([result.stdout.strip()]))
            sid = row[1].strip()
        except Exception as exc:
            raise StorageProtectionError(
                f"Could not resolve current Windows SID from whoami: {result.stdout!r}"
            ) from exc

        if not sid.upper().startswith("S-1-"):
            raise StorageProtectionError(f"Unexpected Windows SID: {sid!r}")
        return sid

    def harden(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        user_sid = self._current_user_sid()
        target = str(path.resolve())

        # Remove inherited ACLs, then explicitly grant only the JARVIS Windows
        # user and LOCAL SYSTEM full control. Numeric SIDs avoid localization.
        self._run(["icacls", target, "/inheritance:r"])
        self._run(
            [
                "icacls",
                target,
                "/grant:r",
                f"*{user_sid}:(OI)(CI)F",
                f"*{self._SYSTEM_SID}:(OI)(CI)F",
            ]
        )

        # Remove common broad read/grant principals if they were explicit.
        # icacls can return a non-zero result when no matching ACE exists, so
        # these removals are best-effort after the restrictive grants above.
        for sid in self._BROAD_SIDS:
            self._run(["icacls", target, "/remove:g", f"*{sid}"], check=False)


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def build_default_protector() -> DataProtector:
    if os.name == "nt":
        return WindowsDpapiProtector()

    if _running_under_pytest():
        return TestOnlyProtector()

    raise StorageProtectionError(
        "JARVIS Web encrypted history is Windows-DPAPI-only in production"
    )


def build_default_acl_hardener() -> DirectoryAclHardener:
    if os.name == "nt":
        return WindowsAclHardener()

    if _running_under_pytest():
        return NoOpAclHardener()

    raise StorageProtectionError(
        "JARVIS Web private storage ACL hardening is Windows-only in production"
    )
