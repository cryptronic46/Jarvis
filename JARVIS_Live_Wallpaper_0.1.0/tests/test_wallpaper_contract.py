import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class WallpaperContractTests(unittest.TestCase):
    def test_audio_listener_is_registered(self):
        js = (ROOT / "wallpaper" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("wallpaperRegisterAudioListener", js)
        self.assertIn("wallpaperAudioListener", js)
        self.assertIn("requestAnimationFrame", js)

    def test_live_api_is_loopback(self):
        js = (ROOT / "wallpaper" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('http://127.0.0.1:8765', js)
        self.assertNotIn("https://", js)

    def test_expected_live_panels_exist(self):
        html = (ROOT / "wallpaper" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="cpuUsage"',
            'id="ramUsage"',
            'id="gpuUsage"',
            'id="download"',
            'id="securityTitle"',
            'id="temperature"',
            'id="humidity"',
            'id="waveHeight"',
            'id="agendaList"',
            'id="coreState"',
        ):
            self.assertIn(marker, html)

    def test_reference_image_bundled(self):
        self.assertTrue(
            (ROOT / "wallpaper" / "assets" / "jarvis_reference.png").exists()
        )


if __name__ == "__main__":
    unittest.main()
