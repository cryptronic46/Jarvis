from __future__ import annotations

"""Inference-only openWakeWord compatibility loader for strict Windows policy.

openWakeWord 0.6.0 exposes custom-verifier *training* from its package
initializer. That optional path imports scikit-learn/SciPy, including native
extensions that may be blocked by Windows Application Control. JARVIS runtime
wake detection does not need that training surface.

This loader executes the installed openWakeWord package initializer after
removing only the custom-verifier training import and its ``__all__`` export.
The official Model, VAD, utils and model metadata are still loaded from the
installed package. No third-party files are modified on disk.
"""

from importlib.machinery import PathFinder
from pathlib import Path
from threading import RLock
from types import ModuleType
from typing import Any
import re
import sys

_LOCK = RLock()
_SENTINEL = "__jarvis_inference_only__"


def _package_spec():
    spec = PathFinder.find_spec("openwakeword", sys.path)
    if spec is None or not spec.submodule_search_locations:
        raise ImportError("openwakeword is not installed")
    return spec


def sanitize_openwakeword_init(source: str) -> str:
    """Remove only the optional custom-verifier training import/export."""
    source = re.sub(
        r"(?m)^\s*from\s+openwakeword\.custom_verifier_model\s+import\s+train_custom_verifier\s*$",
        "",
        source,
    )
    source = re.sub(
        r"(?m)^\s*__all__\s*=\s*\[[^\]]*\]\s*$",
        "__all__ = ['Model', 'VAD']",
        source,
        count=1,
    )
    return source


def _clear_openwakeword_modules() -> None:
    for name in list(sys.modules):
        if name == "openwakeword" or name.startswith("openwakeword."):
            sys.modules.pop(name, None)


def load_openwakeword() -> ModuleType:
    """Load the official openWakeWord inference surface without sklearn/SciPy."""
    with _LOCK:
        existing = sys.modules.get("openwakeword")
        if existing is not None and getattr(existing, _SENTINEL, False):
            return existing

        # Clear a partial ordinary import (for example after a blocked SciPy .pyd).
        _clear_openwakeword_modules()
        spec = _package_spec()
        package_dir = Path(next(iter(spec.submodule_search_locations))).resolve()
        init_path = package_dir / "__init__.py"
        if not init_path.is_file():
            raise ImportError(f"openwakeword __init__.py not found: {init_path}")

        module = ModuleType("openwakeword")
        module.__file__ = str(init_path)
        module.__package__ = "openwakeword"
        module.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
        module.__spec__ = spec
        module.__loader__ = spec.loader
        setattr(module, _SENTINEL, True)
        sys.modules["openwakeword"] = module

        source = sanitize_openwakeword_init(init_path.read_text(encoding="utf-8"))
        try:
            exec(compile(source, str(init_path), "exec"), module.__dict__)
        except Exception:
            _clear_openwakeword_modules()
            raise

        setattr(module, _SENTINEL, True)
        return module


def runtime_classes():
    module = load_openwakeword()
    model = getattr(module, "Model", None)
    vad = getattr(module, "VAD", None)
    if model is None or vad is None:
        raise ImportError("openWakeWord inference classes are unavailable")
    return model, vad


def runtime_probe() -> dict[str, Any]:
    try:
        module = load_openwakeword()
        return {
            "ok": True,
            "inference_only": bool(getattr(module, _SENTINEL, False)),
            "model": bool(getattr(module, "Model", None)),
            "vad": bool(getattr(module, "VAD", None)),
            "custom_verifier_training_loaded": "openwakeword.custom_verifier_model" in sys.modules,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }
