from __future__ import annotations

CURRENT_MARKERS = (
    "atual", "agora", "neste momento", "neste instante",
    "current", "currently", "right now",
)

GPU_MARKERS = ("gpu", "gráfica", "grafica", "rtx", "vram", "temperatura")
PC_MARKERS = ("pc", "computador", "cpu", "ram", "memória", "memoria", "disco")


def requires_current_gpu(text: str) -> bool:
    t = text.lower()
    return any(x in t for x in CURRENT_MARKERS) and any(x in t for x in GPU_MARKERS)


def requires_current_system(text: str) -> bool:
    t = text.lower()
    return any(x in t for x in CURRENT_MARKERS) and any(x in t for x in PC_MARKERS)


def allows_freshness_fallback(
    text: str,
    *,
    semantic_request_present: bool,
) -> bool:
    """Allow heuristic freshness only outside semantic routing."""
    if semantic_request_present:
        return False

    return (
        requires_current_gpu(text)
        or requires_current_system(text)
    )
