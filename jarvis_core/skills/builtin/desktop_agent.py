from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import ctypes
import platform
import subprocess

from jarvis_core.core.subprocess_text import decode_subprocess_stream
import time

from jarvis_core.security.policy import RiskLevel
from jarvis_core.skills.base import Skill, SkillContext, SkillTool


class DesktopAgentService:
    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.screenshot_dir = Path(
            getattr(context.settings, "desktop_agent_screenshot_dir", "memory/screenshots")
        )
        self.max_windows = max(5, min(int(
            getattr(context.settings, "desktop_agent_max_windows", 50)
        ), 100))

    @staticmethod
    def _is_windows() -> bool:
        return platform.system().lower() == "windows"

    def _unsupported(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "WINDOWS_ONLY",
            "message": "O Desktop Agent desta release controla apenas Windows.",
        }

    @staticmethod
    def _user32():
        return ctypes.windll.user32

    @staticmethod
    def _window_title(hwnd: int) -> str:
        user32 = ctypes.windll.user32
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return ""
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value.strip()

    @staticmethod
    def _window_rect(hwnd: int) -> dict[str, int] | None:
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]
        rect = RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return {
            "left": int(rect.left),
            "top": int(rect.top),
            "right": int(rect.right),
            "bottom": int(rect.bottom),
            "width": max(0, int(rect.right - rect.left)),
            "height": max(0, int(rect.bottom - rect.top)),
        }

    def observe(self) -> dict[str, Any]:
        if not self._is_windows():
            return self._unsupported()
        user32 = self._user32()

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        hwnd = int(user32.GetForegroundWindow() or 0)
        return {
            "ok": True,
            "screen": {
                "width": int(user32.GetSystemMetrics(0)),
                "height": int(user32.GetSystemMetrics(1)),
            },
            "cursor": {"x": int(point.x), "y": int(point.y)},
            "foreground": {
                "hwnd": hwnd,
                "title": self._window_title(hwnd) if hwnd else "",
                "rect": self._window_rect(hwnd) if hwnd else None,
            },
            "sampled_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        }

    def list_windows(self, limit: int = 30) -> dict[str, Any]:
        if not self._is_windows():
            return self._unsupported()
        user32 = self._user32()
        rows: list[dict[str, Any]] = []
        cap = max(1, min(int(limit), self.max_windows))
        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            if len(rows) >= cap:
                return False
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                title = self._window_title(int(hwnd))
                if not title:
                    return True
                rows.append({
                    "hwnd": int(hwnd),
                    "title": title,
                    "rect": self._window_rect(int(hwnd)),
                    "foreground": int(hwnd) == int(user32.GetForegroundWindow() or 0),
                })
            except Exception:
                pass
            return True

        user32.EnumWindows(EnumProc(callback), 0)
        return {"ok": True, "count": len(rows), "windows": rows}

    def _find_window(self, title: str) -> dict[str, Any] | None:
        wanted = str(title or "").strip().lower()
        if not wanted:
            return None
        data = self.list_windows(limit=self.max_windows)
        if not data.get("ok"):
            return None
        exact = [row for row in data["windows"] if row["title"].lower() == wanted]
        partial = [row for row in data["windows"] if wanted in row["title"].lower()]
        return (exact or partial or [None])[0]

    def focus_window(self, title: str) -> dict[str, Any]:
        if not self._is_windows():
            return self._unsupported()
        row = self._find_window(title)
        if not row:
            return {"ok": False, "error": "WINDOW_NOT_FOUND", "title": title}
        hwnd = int(row["hwnd"])
        user32 = self._user32()
        try:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ok = bool(user32.SetForegroundWindow(hwnd))
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        self.context.events.emit("DESKTOP_WINDOW_FOCUSED", title=row["title"], hwnd=hwnd)
        return {"ok": ok, "title": row["title"], "hwnd": hwnd, "rect": row.get("rect")}

    def capture_screen(self) -> dict[str, Any]:
        if not self._is_windows():
            return self._unsupported()
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        target = self.screenshot_dir / (
            "screen_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png"
        )
        # Fixed script: the model cannot inject a command or choose an arbitrary
        # output path. The only substituted value is a Core-generated path.
        escaped = str(target.resolve()).replace("'", "''")
        script = rf'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bmp)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save('{escaped}', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose(); $bmp.Dispose()
'''
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                timeout=12,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        if completed.returncode != 0 or not target.is_file():
            return {
                "ok": False,
                "error": "SCREENSHOT_FAILED",
                "returncode": completed.returncode,
                "stderr": decode_subprocess_stream(completed.stderr)[-1200:],
            }
        self.context.events.emit("DESKTOP_SCREEN_CAPTURED", path=str(target), size=target.stat().st_size)
        return {
            "ok": True,
            "path": str(target),
            "size_bytes": target.stat().st_size,
            "captured_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        }

    def move_cursor(self, x: int, y: int) -> dict[str, Any]:
        """Move the pointer without generating any mouse button event."""
        if not self._is_windows():
            return self._unsupported()
        obs = self.observe()
        width = int(obs.get("screen", {}).get("width") or 0)
        height = int(obs.get("screen", {}).get("height") or 0)
        x, y = int(x), int(y)
        if width <= 0 or height <= 0 or not (0 <= x < width and 0 <= y < height):
            return {"ok": False, "error": "COORDINATES_OUT_OF_BOUNDS", "x": x, "y": y}
        ok = bool(self._user32().SetCursorPos(x, y))
        if not ok:
            return {"ok": False, "error": "SET_CURSOR_FAILED", "x": x, "y": y}
        self.context.events.emit("DESKTOP_CURSOR_MOVED", x=x, y=y, clicked=False)
        return {"ok": True, "x": x, "y": y, "clicked": False}

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
        if not self._is_windows():
            return self._unsupported()
        button = str(button or "left").lower()
        flags = {
            "left": (0x0002, 0x0004),
            "right": (0x0008, 0x0010),
            "middle": (0x0020, 0x0040),
        }
        if button not in flags:
            return {"ok": False, "error": "INVALID_MOUSE_BUTTON"}
        obs = self.observe()
        width = int(obs.get("screen", {}).get("width") or 0)
        height = int(obs.get("screen", {}).get("height") or 0)
        x, y = int(x), int(y)
        if width <= 0 or height <= 0 or not (0 <= x < width and 0 <= y < height):
            return {"ok": False, "error": "COORDINATES_OUT_OF_BOUNDS", "x": x, "y": y}
        clicks = max(1, min(int(clicks), 3))
        user32 = self._user32()
        user32.SetCursorPos(x, y)
        down, up = flags[button]
        for idx in range(clicks):
            user32.mouse_event(down, 0, 0, 0, 0)
            user32.mouse_event(up, 0, 0, 0, 0)
            if idx + 1 < clicks:
                time.sleep(0.08)
        self.context.events.emit("DESKTOP_CLICK", x=x, y=y, button=button, clicks=clicks)
        return {"ok": True, "x": x, "y": y, "button": button, "clicks": clicks}

    def type_text(self, text: str, interval_ms: int = 8, window_title: str | None = None) -> dict[str, Any]:
        if not self._is_windows():
            return self._unsupported()
        focused = None
        if str(window_title or "").strip():
            focused = self.focus_window(str(window_title).strip())
            if not focused.get("ok"):
                return {
                    "ok": False,
                    "error": "TARGET_WINDOW_NOT_FOUND",
                    "window_title": str(window_title),
                    "detail": focused,
                }
            time.sleep(0.08)
        value = str(text or "")
        if not value:
            return {"ok": False, "error": "EMPTY_TEXT"}
        if len(value) > 2000:
            return {"ok": False, "error": "TEXT_TOO_LONG", "max_chars": 2000}
        interval = max(0.0, min(float(interval_ms) / 1000.0, 0.25))
        user32 = self._user32()
        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_UNICODE = 0x0004
        for char in value:
            code = ord(char)
            # UTF-16 surrogate pairs for non-BMP characters are sent separately.
            encoded = char.encode("utf-16-le")
            units = [int.from_bytes(encoded[i:i+2], "little") for i in range(0, len(encoded), 2)]
            for unit in units:
                user32.keybd_event(0, unit, KEYEVENTF_UNICODE, 0)
                user32.keybd_event(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            if interval:
                time.sleep(interval)
        self.context.events.emit("DESKTOP_TEXT_TYPED", chars=len(value), window_title=str(window_title or ""))
        return {"ok": True, "chars": len(value), "window_title": (focused or {}).get("title") if focused else None}

    def hotkey(self, keys: list[str], window_title: str | None = None) -> dict[str, Any]:
        if not self._is_windows():
            return self._unsupported()
        if not isinstance(keys, list) or not (1 <= len(keys) <= 4):
            return {"ok": False, "error": "INVALID_HOTKEY"}
        focused = None
        if str(window_title or "").strip():
            focused = self.focus_window(str(window_title).strip())
            if not focused.get("ok"):
                return {"ok": False, "error": "TARGET_WINDOW_NOT_FOUND", "window_title": str(window_title), "detail": focused}
            time.sleep(0.08)
        vk = {
            "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
            "win": 0x5B, "enter": 0x0D, "tab": 0x09, "esc": 0x1B,
            "escape": 0x1B, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
            "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
            "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
            "f4": 0x73, "f5": 0x74,
        }
        for char in "abcdefghijklmnopqrstuvwxyz0123456789":
            vk[char] = ord(char.upper())
        cleaned = [str(k or "").strip().lower() for k in keys]
        if any(k not in vk for k in cleaned):
            return {"ok": False, "error": "HOTKEY_NOT_ALLOWLISTED", "keys": cleaned}
        user32 = self._user32()
        for key in cleaned:
            user32.keybd_event(vk[key], 0, 0, 0)
        for key in reversed(cleaned):
            user32.keybd_event(vk[key], 0, 0x0002, 0)
        self.context.events.emit("DESKTOP_HOTKEY", keys=cleaned, window_title=str(window_title or ""))
        return {"ok": True, "keys": cleaned, "window_title": (focused or {}).get("title") if focused else None}

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "platform": platform.system(),
            "available": self._is_windows(),
            "screenshot_dir": str(self.screenshot_dir),
            "actions": {
                "observe": "read_only",
                "list_windows": "read_only",
                "focus": "low",
                "capture_screen": "low",
                "move_cursor": "low_no_click",
                "click": "confirmation_required",
                "type_text": "confirmation_required",
                "hotkey": "confirmation_required",
            },
        }


class DesktopAgentSkill(Skill):
    skill_id = "desktop_agent"
    name = "Desktop Agent"
    version = "1.0.0"
    description = "Observe and control the Windows desktop with bounded input primitives."

    def __init__(self, context: SkillContext) -> None:
        super().__init__(context)
        self.service = DesktopAgentService(context)

    def tools(self) -> list[SkillTool]:
        return [
            SkillTool("desktop_agent_status", "Read Desktop Agent availability and control boundaries.", self.service.status, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, ("desktop agent", "estado do desktop agent", "status do desktop agent")),
            SkillTool("desktop_observe", "Read screen size, cursor position and the foreground Windows window.", self.service.observe, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, ("janela ativa", "janela principal", "cursor", "observa o desktop", "observa o ecra", "observa o ecrã")),
            SkillTool("desktop_list_windows", "List visible top-level Windows windows and their rectangles.", self.service.list_windows, {"type":"object","properties":{"limit":{"type":"integer","minimum":1,"maximum":50}}}, RiskLevel.READ_ONLY, ("lista as janelas", "janelas abertas", "todas as janelas", "listar janelas")),
            SkillTool("desktop_focus_window", "Bring a visible window matching a title to the foreground.", self.service.focus_window, {"type":"object","properties":{"title":{"type":"string"}},"required":["title"]}, RiskLevel.LOW, ("foca a janela", "focar janela", "traz a janela")),
            SkillTool("desktop_capture_screen", "Capture the current Windows virtual screen to a Core-generated local PNG path.", self.service.capture_screen, {"type":"object","properties":{}}, RiskLevel.LOW, ("screenshot", "captura o ecra", "captura o ecrã", "captura de ecra", "captura de ecrã")),
            SkillTool("desktop_move_cursor", "Move the mouse pointer to bounded screen coordinates without clicking.", self.service.move_cursor, {"type":"object","properties":{"x":{"type":"integer","minimum":0},"y":{"type":"integer","minimum":0}},"required":["x","y"]}, RiskLevel.LOW, ("move o cursor", "mover cursor", "coloca o cursor", "sem clicar")),
            SkillTool("desktop_click", "Click bounded screen coordinates. Requires OWNER confirmation because UI clicks can cause consequential actions.", self.service.click, {"type":"object","properties":{"x":{"type":"integer","minimum":0},"y":{"type":"integer","minimum":0},"button":{"type":"string","enum":["left","right","middle"]},"clicks":{"type":"integer","minimum":1,"maximum":3}},"required":["x","y"]}, RiskLevel.CONFIRM, ("clica", "click", "carrega em", "rato")),
            SkillTool("desktop_type_text", "Type literal text into a Windows control; optionally focus a named visible window immediately before typing. Requires OWNER confirmation.", self.service.type_text, {"type":"object","properties":{"text":{"type":"string","maxLength":2000},"interval_ms":{"type":"integer","minimum":0,"maximum":250},"window_title":{"type":"string","maxLength":300}},"required":["text"]}, RiskLevel.CONFIRM, ("escreve no pc", "escreve no", "escreve", "digita", "digitar", "teclado")),
            SkillTool("desktop_hotkey", "Press an allowlisted Windows keyboard shortcut; optionally focus a named visible window first. Requires OWNER confirmation.", self.service.hotkey, {"type":"object","properties":{"keys":{"type":"array","items":{"type":"string"},"minItems":1,"maxItems":4},"window_title":{"type":"string","maxLength":300}},"required":["keys"]}, RiskLevel.CONFIRM, ("atalho", "hotkey", "ctrl+", "pressiona ctrl", "prime ctrl", "premir ctrl")),
        ]

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["service"] = self.service.status()
        return data


def create_skill(context: SkillContext) -> Skill:
    skill = DesktopAgentSkill(context)
    # Make the service discoverable by Vision and Task Planner through context.
    context.services["desktop_agent"] = skill.service
    return skill
