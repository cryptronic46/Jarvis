from __future__ import annotations

import asyncio
import ctypes
import hashlib
import shutil
import re
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from tempfile import gettempdir
from threading import Event as ThreadEvent, Lock, Thread
from time import sleep, monotonic
from uuid import uuid4
from typing import Any

from jarvis_core.core.events import EventBus
from jarvis_core.services.speech_text import prepare_for_speech_chunks


@dataclass(slots=True)
class SpeechConfig:
    enabled: bool = True
    backend: str = "auto"  # auto | edge | sapi
    edge_voice: str = "pt-PT-RaquelNeural"
    rate: str = "-9%"
    pitch: str = "-8Hz"
    persona_profile: str = "velvet_feminine"
    sapi_prefer_gender: str = "Female"
    volume: str = "+0%"
    max_chars: int = 1600
    fallback_sapi: bool = True
    cache_enabled: bool = True
    cache_dir: str = ".cache/tts"
    cache_max_bytes: int = 256 * 1024 * 1024
    cache_max_files: int = 500


class SpeechService:
    """
    Independent TTS pipeline.

    Primary: Edge neural TTS.
    Playback: built-in Windows MCI (no VLC/ffmpeg required).
    Fallback: Windows SAPI via COM.

    This service never blocks the JARVIS agent loop.
    """

    def __init__(self, events: EventBus, config: SpeechConfig):
        self.events = events
        self.config = config
        self._queue: Queue[str] = Queue()
        self._shutdown = ThreadEvent()
        self._cancel_current = ThreadEvent()
        self._thread = Thread(target=self._worker, name="jarvis-speech", daemon=True)
        self._lock = Lock()
        self._active_alias: str | None = None
        self._playback_ready = ThreadEvent()
        self._bargein_paused = False
        self._speaking = False
        self._last_backend: str | None = None
        self._last_error: str | None = None
        self._cache_dir = Path(self.config.cache_dir)
        if self.config.cache_enabled:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._prune_cache()


    def _prune_cache(self) -> dict[str, int]:
        """Bound the persistent Edge-TTS cache by file count and bytes.

        Oldest MP3 entries are removed first. Temporary synthesis files live in
        the OS temp directory and are not touched here.
        """
        if not self.config.cache_enabled or not self._cache_dir.exists():
            return {"files": 0, "bytes": 0, "removed": 0}
        rows = []
        total = 0
        for path in self._cache_dir.glob("*.mp3"):
            try:
                stat = path.stat()
            except OSError:
                continue
            rows.append((stat.st_mtime, stat.st_size, path))
            total += int(stat.st_size)
        rows.sort(key=lambda row: row[0])
        max_files = max(1, int(self.config.cache_max_files))
        max_bytes = max(16 * 1024 * 1024, int(self.config.cache_max_bytes))
        removed = 0
        while rows and (len(rows) > max_files or total > max_bytes):
            _mtime, size, path = rows.pop(0)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            total -= int(size)
            removed += 1
        if removed:
            self.events.emit("TTS_CACHE_PRUNED", removed=removed, files=len(rows), bytes=total)
        return {"files": len(rows), "bytes": max(0, total), "removed": removed}

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._thread.start()
        self.events.emit(
            "SPEECH_SERVICE_STARTED",
            enabled=self.config.enabled,
            backend=self.config.backend,
            voice=self.config.edge_voice,
        )

    def shutdown(self) -> None:
        self.stop(clear_queue=True)
        self._shutdown.set()
        self._queue.put("")
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        self.events.emit("SPEECH_SERVICE_STOPPED")

    def say(self, text: str) -> bool:
        if not self.config.enabled:
            return False
        self.events.emit("TTS_REQUESTED", chars=len(text))
        chunks = prepare_for_speech_chunks(
            text,
            max_chars=self.config.max_chars,
        )
        if not chunks:
            return False
        for chunk in chunks:
            self._queue.put(chunk)
        self.events.emit(
            "SPEECH_QUEUED",
            chars=sum(len(chunk) for chunk in chunks),
            chunks=len(chunks),
        )
        return True

    def stop(self, clear_queue: bool = False) -> None:
        self._cancel_current.set()
        self._bargein_paused = False
        self._stop_mci_playback()

        if clear_queue:
            try:
                while True:
                    self._queue.get_nowait()
                    self._queue.task_done()
            except Empty:
                pass
        self.events.emit("SPEECH_INTERRUPTED", cleared_queue=clear_queue)

    def pause_for_bargein(self) -> bool:
        """Temporarily pause active Edge/MCI playback for voice verification."""
        with self._lock:
            alias = self._active_alias
        if (
            not self._speaking
            or self._cancel_current.is_set()
            or not alias
            or self._bargein_paused
        ):
            return False
        # ``_active_alias`` can exist a few milliseconds before MCI has fully
        # opened the device. Waiting briefly avoids the observed MCI 263 race
        # ("device not open") without delaying normal interaction.
        if not self._playback_ready.wait(timeout=0.15):
            return False
        try:
            mode = self._mci(f"status {alias} mode", 64).strip().lower()
            if mode not in {"playing", "paused"}:
                return False
            if mode != "paused":
                self._mci(f"pause {alias}")
            self._bargein_paused = True
            self.events.emit("SPEECH_BARGEIN_PAUSED", alias=alias)
            return True
        except Exception as exc:
            self.events.emit(
                "SPEECH_BARGEIN_PAUSE_FAILED",
                error=f"{type(exc).__name__}: {exc}",
            )
            return False

    def resume_after_bargein(self) -> bool:
        """Resume playback after a false barge-in candidate."""
        with self._lock:
            alias = self._active_alias
        if (
            not self._bargein_paused
            or self._cancel_current.is_set()
            or not alias
        ):
            self._bargein_paused = False
            return False
        try:
            if not self._playback_ready.is_set():
                self._bargein_paused = False
                return False
            mode = self._mci(f"status {alias} mode", 64).strip().lower()
            if mode == "paused":
                self._mci(f"resume {alias}")
            elif mode != "playing":
                self._bargein_paused = False
                return False
            self._bargein_paused = False
            self.events.emit("SPEECH_BARGEIN_RESUMED", alias=alias)
            return True
        except Exception as exc:
            self._bargein_paused = False
            self.events.emit(
                "SPEECH_BARGEIN_RESUME_FAILED",
                error=f"{type(exc).__name__}: {exc}",
            )
            return False

    def set_enabled(self, enabled: bool) -> None:
        self.config.enabled = bool(enabled)
        if not enabled:
            self.stop(clear_queue=True)
        self.events.emit("SPEECH_ENABLED_CHANGED", enabled=self.config.enabled)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "configured_backend": self.config.backend,
            "edge_voice": self.config.edge_voice,
            "persona_profile": self.config.persona_profile,
            "sapi_prefer_gender": self.config.sapi_prefer_gender,
            "rate": self.config.rate,
            "pitch": self.config.pitch,
            "volume": self.config.volume,
            "speaking": self._speaking,
            "queued": self._queue.qsize(),
            "last_backend": self._last_backend,
            "last_error": self._last_error,
        }

    def test_phrase(self) -> None:
        self.say(
            "Sistemas online, Senhor. Núcleo operacional. "
            "Estou pronta para receber instruções."
        )

    def _worker(self) -> None:
        while not self._shutdown.is_set():
            try:
                text = self._queue.get(timeout=0.25)
            except Empty:
                continue

            if self._shutdown.is_set():
                self._queue.task_done()
                break
            if not text:
                self._queue.task_done()
                continue

            self._cancel_current.clear()
            self._bargein_paused = False
            self._speaking = True
            self.events.emit("SPEECH_STARTED", chars=len(text))
            success = False
            backend_used = None
            error = None

            try:
                if self.config.backend in {"auto", "edge"}:
                    try:
                        self._speak_edge(text)
                        success = not self._cancel_current.is_set()
                        backend_used = "edge"
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        self.events.emit("SPEECH_BACKEND_FAILED", backend="edge", error=error)
                        if self.config.backend == "edge" and not self.config.fallback_sapi:
                            raise

                if (
                    not success
                    and not self._cancel_current.is_set()
                    and self.config.fallback_sapi
                    and self.config.backend in {"auto", "sapi", "edge"}
                ):
                    try:
                        self._speak_sapi(text)
                        success = not self._cancel_current.is_set()
                        backend_used = "sapi"
                        error = None
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        self.events.emit("SPEECH_BACKEND_FAILED", backend="sapi", error=error)

            finally:
                self._last_backend = backend_used
                self._last_error = error
                self._bargein_paused = False
                self._speaking = False
                self.events.emit(
                    "SPEECH_FINISHED",
                    ok=success,
                    backend=backend_used,
                    error=error,
                )
                self._queue.task_done()

    def _edge_segments(self, text: str) -> list[str]:
        """Short first segment for low perceived latency; larger later pieces."""
        value = str(text or "").strip()
        if not value:
            return []
        sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", value) if part.strip()]
        if not sentences:
            sentences = [value]
        out: list[str] = []
        target = 240
        current = ""
        for sentence in sentences:
            words = sentence.split()
            pieces: list[str] = []
            buf = ""
            limit = target if not out and not current else 620
            for word in words:
                candidate = f"{buf} {word}".strip()
                if buf and len(candidate) > limit:
                    pieces.append(buf)
                    buf = word
                    limit = 620
                else:
                    buf = candidate
            if buf:
                pieces.append(buf)
            for piece in pieces:
                limit = target if not out and not current else 620
                candidate = f"{current} {piece}".strip() if current else piece
                if current and len(candidate) > limit:
                    out.append(current)
                    current = piece
                else:
                    current = candidate
        if current:
            out.append(current)
        return out

    def _edge_cache_path(self, text: str) -> Path | None:
        if not self.config.cache_enabled:
            return None
        key_material = "|".join([
            self.config.edge_voice,
            self.config.rate,
            self.config.pitch,
            self.config.volume,
            text,
        ]).encode("utf-8")
        return self._cache_dir / f"{hashlib.sha256(key_material).hexdigest()}.mp3"

    def _synthesize_edge_segment(self, text: str, *, first: bool = False) -> tuple[Path, bool]:
        import edge_tts
        cache_path = self._edge_cache_path(text)
        if cache_path is not None and cache_path.exists() and cache_path.stat().st_size > 0:
            self.events.emit("TTS_CACHE_HIT", chars=len(text))
            if first:
                self.events.emit("TTS_FIRST_CHUNK_READY", chars=len(text), cached=True, elapsed_ms=0)
            else:
                self.events.emit("TTS_NEXT_CHUNK_READY", chars=len(text), cached=True)
            return cache_path, True

        temp = Path(gettempdir()) / f"jarvis_voice_{uuid4().hex}.mp3"
        started = monotonic()
        self.events.emit("TTS_SYNTH_STARTED", chars=len(text), first=first)

        async def synthesize():
            communicator = edge_tts.Communicate(
                text=text,
                voice=self.config.edge_voice,
                rate=self.config.rate,
                volume=self.config.volume,
                pitch=self.config.pitch,
            )
            await communicator.save(str(temp))

        asyncio.run(synthesize())
        elapsed_ms = int((monotonic() - started) * 1000)
        self.events.emit(
            "TTS_FIRST_CHUNK_READY" if first else "TTS_NEXT_CHUNK_READY",
            chars=len(text), cached=False, elapsed_ms=elapsed_ms,
        )
        return temp, False

    def _cache_edge_segment_after_playback(self, path: Path, text: str, was_cached: bool) -> None:
        if was_cached or self._cancel_current.is_set():
            return
        cache_path = self._edge_cache_path(text)
        if cache_path is None:
            return
        try:
            shutil.copyfile(path, cache_path)
        except OSError:
            return
        # Pruning is intentionally outside the first-audio critical path.
        try:
            self._prune_cache()
        except Exception:
            pass

    def _speak_edge(self, text: str) -> None:
        segments = self._edge_segments(text)
        if not segments:
            return

        # Synthesise only the short first segment before playback. While it is
        # playing, prefetch the next segment in a background thread.
        current_path, current_cached = self._synthesize_edge_segment(segments[0], first=True)
        current_text = segments[0]

        for index in range(len(segments)):
            if self._cancel_current.is_set():
                break

            next_result: dict[str, Any] = {}
            next_thread: Thread | None = None
            if index + 1 < len(segments):
                next_text = segments[index + 1]

                def prepare_next(value: str = next_text) -> None:
                    try:
                        path, cached = self._synthesize_edge_segment(value, first=False)
                        next_result.update(path=path, cached=cached, text=value)
                    except Exception as exc:
                        next_result.update(error=exc, text=value)

                next_thread = Thread(target=prepare_next, name="jarvis-tts-prefetch", daemon=True)
                next_thread.start()

            try:
                self._play_mp3_windows(current_path)
            finally:
                self._cache_edge_segment_after_playback(current_path, current_text, current_cached)
                if not current_cached:
                    try:
                        current_path.unlink(missing_ok=True)
                    except OSError:
                        pass

            if next_thread is None:
                break
            next_thread.join()
            if next_result.get("error") is not None:
                raise next_result["error"]
            current_path = next_result["path"]
            current_cached = bool(next_result["cached"])
            current_text = str(next_result["text"])

    def _mci(self, command: str, return_chars: int = 0) -> str:
        if not hasattr(ctypes, "windll"):
            raise RuntimeError("Windows MCI is unavailable on this platform.")

        winmm = ctypes.windll.winmm
        if return_chars:
            buf = ctypes.create_unicode_buffer(return_chars)
            code = winmm.mciSendStringW(command, buf, return_chars, None)
            if code != 0:
                raise RuntimeError(f"MCI error {code} for command: {command}")
            return buf.value

        code = winmm.mciSendStringW(command, None, 0, None)
        if code != 0:
            raise RuntimeError(f"MCI error {code} for command: {command}")
        return ""

    def _play_mp3_windows(self, path: Path) -> None:
        alias = f"jarvis_{uuid4().hex[:10]}"
        safe_path = str(path).replace('"', "")
        self._playback_ready.clear()

        try:
            self._mci(f'open "{safe_path}" type mpegvideo alias {alias}')
            with self._lock:
                self._active_alias = alias
            self._mci(f"play {alias}")
            self._playback_ready.set()
            self.events.emit("PLAYBACK_STARTED", alias=alias, path=str(path))

            while not self._cancel_current.is_set():
                mode = self._mci(f"status {alias} mode", 64).strip().lower()
                if mode not in {"playing", "paused"}:
                    break
                sleep(0.05)
        finally:
            try:
                self._mci(f"stop {alias}")
            except Exception:
                pass
            try:
                self._mci(f"close {alias}")
            except Exception:
                pass
            self._playback_ready.clear()
            with self._lock:
                if self._active_alias == alias:
                    self._active_alias = None

    def _stop_mci_playback(self) -> None:
        with self._lock:
            alias = self._active_alias
        if not alias:
            return
        try:
            self._mci(f"stop {alias}")
        except Exception:
            pass

    def _speak_sapi(self, text: str) -> None:
        import comtypes.client

        speaker = comtypes.client.CreateObject("SAPI.SpVoice")

        # Prefer a Portuguese local voice matching the configured gender.
        # If Windows exposes no gender metadata, fall back to any pt-PT voice.
        try:
            voices = speaker.GetVoices()
            selected = None
            portuguese_fallback = None
            wanted_gender = str(self.config.sapi_prefer_gender or "").lower().strip()
            for i in range(voices.Count):
                token = voices.Item(i)
                description = str(token.GetDescription()).lower()
                if not any(x in description for x in ("portugu", "portugal", "pt-pt")):
                    continue
                if portuguese_fallback is None:
                    portuguese_fallback = token
                gender = ""
                try:
                    gender = str(token.GetAttribute("Gender") or "").lower().strip()
                except Exception:
                    pass
                if wanted_gender and gender == wanted_gender:
                    selected = token
                    break
            if selected is None:
                selected = portuguese_fallback
            if selected is not None:
                speaker.Voice = selected
        except Exception:
            pass

        # SAPI rate scale is -10..10. Keep it calm and deliberate.
        try:
            speaker.Rate = -1
        except Exception:
            pass

        if self._cancel_current.is_set():
            return
        speaker.Speak(text)
