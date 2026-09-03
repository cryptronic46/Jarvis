from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import re
import unicodedata

from jarvis_core.core.local_vision import NativeVisionClient
from jarvis_core.security.policy import RiskLevel
from jarvis_core.skills.base import Skill, SkillContext, SkillTool


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


class VisionService:
    """Local-only screen/camera capture with optional JARVIS-owned native visual inference."""

    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.model = str(getattr(context.settings, "vision_model", "Qwen2.5-VL-3B-Instruct-Q4_K_M") or "").strip()
        self.enabled = bool(getattr(context.settings, "vision_enabled", True))
        self.camera_enabled = bool(getattr(context.settings, "vision_camera_enabled", True))
        self.camera_index = int(getattr(context.settings, "vision_camera_index", 0))
        self.camera_auto_detect = bool(getattr(context.settings, "vision_camera_auto_detect", True))
        self.camera_probe_limit = max(1, min(int(getattr(context.settings, "vision_camera_probe_limit", 5)), 12))
        self.keep_alive = str(getattr(context.settings, "vision_keep_alive", "2m") or "2m").strip()
        self.capture_dir = Path(getattr(context.settings, "vision_capture_dir", "memory/vision"))
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.native = NativeVisionClient(context.settings, context.events)
        self.last_path: str | None = None
        self.last_source: str | None = None
        self.last_analysis: dict[str, Any] | None = None

    def _desktop(self):
        return self.context.services.get("desktop_agent")

    def _model_available(self) -> tuple[bool, str | None]:
        if not self.enabled:
            return False, "VISION_DISABLED"
        if not self.model:
            return False, "VISION_MODEL_NOT_CONFIGURED"
        return self.native.configured()

    @staticmethod
    def _camera_dependency() -> tuple[bool, str | None]:
        try:
            import cv2  # type: ignore  # noqa: F401
            return True, None
        except Exception:
            return False, "OPENCV_NOT_INSTALLED"

    def status(self) -> dict[str, Any]:
        available, error = self._model_available()
        camera_dep, camera_error = self._camera_dependency()
        desktop = self._desktop()
        runtime = self.native.runtime.status()
        return {
            "ok": True,
            "enabled": self.enabled,
            "model": self.model,
            "backend": "jarvis_native_multimodal",
            "model_available": available,
            "model_error": error,
            "model_path": str(self.native.runtime.model_path),
            "mmproj_path": str(self.native.runtime.mmproj_path),
            "runtime_running": bool(runtime.running),
            "runtime_pid": runtime.pid,
            "runtime_url": runtime.url,
            "vision_keep_alive": self.keep_alive,
            "desktop_capture_available": bool(desktop),
            "camera_enabled": self.camera_enabled,
            "camera_index": self.camera_index,
            "camera_auto_detect": self.camera_auto_detect,
            "camera_probe_limit": self.camera_probe_limit,
            "camera_dependency_available": camera_dep,
            "camera_error": camera_error,
            "last_capture": self.last_path,
            "last_source": self.last_source,
            "local_only": True,
            "external_ai": False,
            "setup": ".\\setup_vision.ps1" if (not available or (self.camera_enabled and not camera_dep)) else None,
        }

    def capture(self) -> dict[str, Any]:
        desktop = self._desktop()
        if desktop is None:
            return {"ok": False, "error": "DESKTOP_AGENT_UNAVAILABLE"}
        result = desktop.capture_screen()
        if result.get("ok"):
            self.last_path = str(result.get("path"))
            self.last_source = "screen"
            self.context.events.emit("VISION_CAPTURED", path=self.last_path, source="screen")
        return result

    def list_cameras(self) -> dict[str, Any]:
        if not self.camera_enabled:
            return {"ok": False, "error": "CAMERA_VISION_DISABLED", "cameras": []}
        dep, error = self._camera_dependency()
        if not dep:
            return {"ok": False, "error": error, "cameras": []}
        try:
            import cv2  # type: ignore
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc), "cameras": []}

        rows = []
        for index in range(self.camera_probe_limit):
            cap = cv2.VideoCapture(index)
            try:
                if not cap.isOpened():
                    continue
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                height, width = frame.shape[:2]
                rows.append({
                    "index": index,
                    "width": int(width),
                    "height": int(height),
                    "configured": index == int(self.camera_index),
                })
            finally:
                cap.release()
        return {"ok": True, "cameras": rows, "configured_index": self.camera_index}

    def set_camera_index(self, index: int) -> dict[str, Any]:
        value = max(0, min(int(index), 11))
        self.camera_index = value
        try:
            self.context.settings.vision_camera_index = value
        except Exception:
            pass
        return {"ok": True, "camera_index": value}

    def _camera_candidates(self, requested: int | None = None) -> list[int]:
        first = self.camera_index if requested is None else max(0, min(int(requested), 11))
        rows = [first]
        if self.camera_auto_detect and requested is None:
            rows.extend(i for i in range(self.camera_probe_limit) if i != first)
        return rows

    def capture_camera(self, camera_index: int | None = None) -> dict[str, Any]:
        if not self.camera_enabled:
            return {"ok": False, "error": "CAMERA_VISION_DISABLED"}
        dep, error = self._camera_dependency()
        if not dep:
            return {
                "ok": False,
                "error": error,
                "message": "A visão por câmara requer OpenCV local. Executa .\\setup_vision.ps1.",
            }
        try:
            import cv2  # type: ignore
            frame = None
            index = None
            attempted = []
            for candidate in self._camera_candidates(camera_index):
                attempted.append(candidate)
                cap = cv2.VideoCapture(candidate)
                try:
                    if not cap.isOpened():
                        continue
                    ok, candidate_frame = cap.read()
                    if not ok or candidate_frame is None:
                        continue
                    frame = candidate_frame
                    index = candidate
                    break
                finally:
                    cap.release()
            if frame is None or index is None:
                return {
                    "ok": False,
                    "error": "CAMERA_NOT_AVAILABLE",
                    "camera_index": self.camera_index if camera_index is None else camera_index,
                    "attempted": attempted,
                }
            if camera_index is None and index != self.camera_index:
                self.camera_index = int(index)
                try:
                    self.context.settings.vision_camera_index = int(index)
                except Exception:
                    pass
                self.context.events.emit("VISION_CAMERA_RECOVERED", camera_index=index, attempted=attempted)
            path = self.capture_dir / f"camera_{_stamp()}.jpg"
            if not cv2.imwrite(str(path), frame):
                return {"ok": False, "error": "CAMERA_WRITE_FAILED", "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        self.last_path = str(path)
        self.last_source = "camera"
        self.context.events.emit("VISION_CAPTURED", path=self.last_path, source="camera", camera_index=index)
        return {"ok": True, "path": str(path), "source": "camera", "camera_index": index}

    @staticmethod
    def _norm(value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9+]+", " ", text).strip()

    def _screen_grounding_context(self) -> tuple[list[str], list[str]]:
        desktop = self._desktop()
        if desktop is None or not hasattr(desktop, "list_windows"):
            return [], []
        try:
            data = desktop.list_windows()
        except Exception:
            return [], []
        rows = list(data.get("windows") or data.get("value") or []) if isinstance(data, dict) else []
        titles: list[str] = []
        for row in rows:
            title = str(row.get("title") or "") if isinstance(row, dict) else str(row or "")
            title = title.strip()
            if title and title not in titles:
                titles.append(title)
        anchors: list[str] = []
        for title in titles:
            norm = self._norm(title)
            for marker in ("powershell", "brave", "chatgpt", "notepad++", "notepad", "bloco de notas", "visual studio code", "vscode", "discord", "spotify", "steam"):
                if marker in norm and marker not in anchors:
                    anchors.append(marker)
        return titles[:12], anchors[:8]

    def _screen_analysis_grounded(self, text: str, anchors: list[str]) -> bool:
        if not anchors:
            return True
        norm = self._norm(text)
        aliases = {
            "notepad": ("notepad", "bloco de notas"),
            "bloco de notas": ("notepad", "bloco de notas"),
            "visual studio code": ("visual studio code", "vscode", "code"),
        }
        return any(any(candidate in norm for candidate in aliases.get(anchor, (anchor,))) for anchor in anchors)

    def _analyze_path(self, path: Path, prompt: str, source: str) -> dict[str, Any]:
        available, error = self._model_available()
        if not available:
            return {
                "ok": False,
                "error": error,
                "model": self.model,
                "message": (
                    "A captura local está pronta, mas o modelo visual local ainda não está instalado. "
                    "Executa .\\setup_vision.ps1 para descarregar e verificar o modelo multimodal GGUF do JARVIS."
                ),
            }
        if not path.is_file():
            return {"ok": False, "error": "IMAGE_NOT_FOUND", "path": str(path)}
        question = str(prompt or "").strip()[:3000]
        titles, anchors = self._screen_grounding_context() if source == "screen" else ([], [])
        if titles:
            question += (
                "\n\nMETADADOS LOCAIS DE CONTROLO (não substituem a imagem): títulos de janelas atualmente "
                "visíveis/abertas segundo o Windows: " + " | ".join(titles) + ". "
                "Usa-os apenas para evitar descrever uma aplicação que contradiga claramente a captura."
            )
        system = (
            "És o módulo local de visão do JARVIS. Analisa apenas a imagem fornecida. Não tens ferramentas nesta "
            "chamada e não executes ações. Distingue claramente factos visíveis de inferências. Não identifiques uma "
            "pessoa real pelo rosto nem deduzas atributos sensíveis. Quando texto ou detalhes forem ambíguos, diz que "
            "não tens certeza em vez de inventar. Não inventes formulários, notificações, aplicações ou texto que não "
            "consigas observar. Responde em português europeu."
        )
        try:
            text = self.native.analyze(path, prompt=question, system=system)
            if source == "screen" and anchors and not self._screen_analysis_grounded(text, anchors):
                self.context.events.emit("VISION_GROUNDING_RETRY", path=str(path), anchors=anchors)
                retry_prompt = (
                    question + "\n\nA primeira descrição não correspondeu aos títulos de janelas observados pelo próprio Windows. "
                    "Reanalisa a IMAGEM ATUAL desde o início. Identifica pelo menos uma das aplicações visíveis "
                    f"quando ela estiver realmente na imagem: {', '.join(anchors)}. Se não conseguires confirmar, diz explicitamente que a análise visual é inconclusiva."
                )
                text = self.native.analyze(path, prompt=retry_prompt, system=system)
                if not self._screen_analysis_grounded(text, anchors):
                    return {
                        "ok": False,
                        "error": "VISION_GROUNDING_MISMATCH",
                        "message": "A captura foi feita, mas a análise visual não corresponde aos metadados locais das janelas; rejeitei a descrição para não inventar conteúdo do ecrã.",
                        "model": self.model,
                        "backend": "jarvis_native_multimodal",
                        "path": str(path),
                        "source": source,
                        "external_ai": False,
                    }
        except Exception as exc:
            return {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
                "model": self.model,
                "backend": "jarvis_native_multimodal",
            }
        result = {
            "ok": True,
            "model": self.model,
            "backend": "jarvis_native_multimodal",
            "path": str(path),
            "source": source,
            "analysis": text,
            "external_ai": False,
        }
        self.last_analysis = result
        self.context.events.emit("VISION_ANALYZED", path=str(path), source=source, model=self.model, chars=len(text))
        return result

    def shutdown(self, reason: str = "shutdown") -> dict[str, Any]:
        return self.native.shutdown(reason=reason)

    def analyze(
        self,
        prompt: str = "Descreve o que está visível no ecrã e identifica elementos úteis para a tarefa atual.",
        fresh_capture: bool = True,
    ) -> dict[str, Any]:
        if fresh_capture or not self.last_path or self.last_source != "screen" or not Path(self.last_path).is_file():
            captured = self.capture()
            if not captured.get("ok"):
                return captured
        return self._analyze_path(Path(str(self.last_path)), prompt, "screen")

    def analyze_camera(
        self,
        prompt: str = "Descreve objetivamente o que está visível na imagem da câmara e os elementos relevantes.",
        camera_index: int | None = None,
    ) -> dict[str, Any]:
        captured = self.capture_camera(camera_index)
        if not captured.get("ok"):
            return captured
        return self._analyze_path(Path(str(captured["path"])), prompt, "camera")


class VisionSkill(Skill):
    skill_id = "vision"
    name = "Local Vision"
    version = "1.3.0"
    description = "Capture the Windows screen or local camera and optionally understand it with a JARVIS-owned native visual runtime."

    def __init__(self, context: SkillContext) -> None:
        super().__init__(context)
        self.service = VisionService(context)
        context.services["vision"] = self.service

    def tools(self) -> list[SkillTool]:
        screen = ("vê o ecrã", "ve o ecra", "olha para o ecrã", "olha para o ecra", "screenshot", "captura ecrã", "captura ecra", "visão", "visao", "o que está no ecrã", "o que esta no ecra")
        camera = ("câmara", "camara", "webcam", "vê pela câmara", "ve pela camara", "olha pela câmara", "olha pela camara")
        all_markers = tuple(dict.fromkeys(screen + camera))
        return [
            SkillTool("get_vision_status", "Read local screen/camera vision readiness and configured local model.", self.service.status, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, all_markers),
            SkillTool("list_local_cameras", "List local camera indexes that can currently open and capture a frame.", self.service.list_cameras, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, camera),
            SkillTool("capture_current_screen", "Capture the current Windows screen to a local JARVIS image without analyzing it.", self.service.capture, {"type":"object","properties":{}}, RiskLevel.LOW, screen),
            SkillTool("analyze_current_screen", "Capture and analyze the current Windows screen using the configured JARVIS-owned native visual runtime. No external provider is used.", self.service.analyze, {"type":"object","properties":{"prompt":{"type":"string"},"fresh_capture":{"type":"boolean"}}}, RiskLevel.LOW, screen),
            SkillTool("capture_camera_frame", "Capture one frame from the OWNER's configured local camera into JARVIS local storage; no external provider is used.", self.service.capture_camera, {"type":"object","properties":{"camera_index":{"type":"integer","minimum":0,"maximum":8}}}, RiskLevel.LOW, camera),
            SkillTool("analyze_camera_frame", "Capture one local camera frame and analyze it using the configured JARVIS-owned native visual runtime.", self.service.analyze_camera, {"type":"object","properties":{"prompt":{"type":"string"},"camera_index":{"type":"integer","minimum":0,"maximum":8}}}, RiskLevel.LOW, camera),
        ]

    def stop(self) -> None:
        try:
            self.service.shutdown(reason="skill_stop")
        finally:
            super().stop()

    def status(self) -> dict[str, Any]:
        data = super().status(); data["service"] = self.service.status(); return data


def create_skill(context: SkillContext) -> Skill:
    return VisionSkill(context)
