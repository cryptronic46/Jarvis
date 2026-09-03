import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jarvis_core.core.events import Event
from jarvis_core.skills.builtin.wallpaper_live import LiveWallpaperStateService


class DummyEvents:
    def subscribe(self, cb):
        self.cb = cb
    def emit(self, *args, **kwargs):
        return None

class DummyRegistry:
    def describe(self):
        return []


class WallpaperEventIOTests(unittest.TestCase):
    def test_event_callback_does_not_flush_to_disk_synchronously(self):
        with tempfile.TemporaryDirectory() as td:
            settings = SimpleNamespace(
                wallpaper_live_state_path=str(Path(td) / "live_hud.json"),
                wallpaper_live_interval_seconds=2.0,
            )
            context = SimpleNamespace(settings=settings, events=DummyEvents(), registry=DummyRegistry())
            svc = LiveWallpaperStateService(context)
            svc._active = True
            calls = []
            svc._flush = lambda: calls.append("flush")
            svc._on_event(Event(name="WAKE_WORD_DETECTED", timestamp="now", data={}))
            self.assertEqual(calls, [])
            self.assertTrue(svc._dirty.is_set())

if __name__ == "__main__":
    unittest.main()
