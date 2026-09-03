import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis_core.core.events import EventBus
from jarvis_core.services.desktop_integration import DesktopIntegrationService


class DesktopIntegrationTests(unittest.TestCase):
    def make_service(self, root: Path, wallpaper: Path):
        return DesktopIntegrationService(
            EventBus(str(root / "logs")),
            core_root=root,
            wallpaper_root=wallpaper,
            bridge_port=8765,
        )

    def test_bridge_is_loopback_only_and_uses_no_shell(self):
        source = Path("jarvis_core/services/desktop_integration.py").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1", source)
        self.assertIn("shell=False", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)

    def test_missing_addon_fails_soft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "core"; root.mkdir()
            wall = Path(tmp) / "wall"
            svc = self.make_service(root, wall)
            with patch.object(svc, "_bridge_online", return_value=False), patch("platform.system", return_value="Linux"):
                result = svc.start()
            self.assertFalse(result["bridge_online"])
            self.assertEqual(result["last_error"], "WALLPAPER_BRIDGE_NOT_INSTALLED")

    def test_existing_bridge_is_not_started_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "core"; root.mkdir()
            wall = Path(tmp) / "wall"; wall.mkdir()
            svc = self.make_service(root, wall)
            with patch.object(svc, "_bridge_online", return_value=True), patch("platform.system", return_value="Linux"), patch("subprocess.Popen") as popen:
                result = svc.start()
            popen.assert_not_called()
            self.assertTrue(result["bridge_online"])

    def test_config_has_desktop_defaults(self):
        text = Path("jarvis_core/core/config.py").read_text(encoding="utf-8")
        for item in (
            "desktop_integration_enabled",
            "desktop_wallpaper_root",
            "desktop_bridge_auto_start",
            "desktop_bridge_port",
            "desktop_wallpaper_engine_auto_start",
        ):
            self.assertIn(item, text)

    def test_cli_exposes_owner_diagnostics(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('/desktop status', text)
        self.assertIn('/desktop ensure', text)
        self.assertIn('desktop.start()', text)


if __name__ == "__main__":
    unittest.main()
