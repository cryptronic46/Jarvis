import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_core.tools.windows_actions import AppRegistry, _expand_windows_env


class AppDiscoveryTests(unittest.TestCase):
    def test_windows_percent_environment_expansion(self):
        with patch.dict(os.environ, {"ProgramFiles": r"C:\Program Files"}, clear=False):
            self.assertEqual(
                _expand_windows_env(r"%ProgramFiles%\Brave\brave.exe"),
                r"C:\Program Files\Brave\brave.exe"
            )

    def test_path_candidate_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "brave.exe"
            exe.write_text("fake", encoding="utf-8")
            cfg = Path(d) / "apps.json"
            cfg.write_text(json.dumps({
                "apps": {"brave": {
                    "name": "Brave",
                    "aliases": ["browser"],
                    "path_candidates": [str(exe)],
                    "executable_candidates": ["brave.exe"],
                    "process_names": ["brave.exe"],
                    "launch": {"type": "path", "target": str(exe)}
                }}
            }), encoding="utf-8")
            registry = AppRegistry(cfg)
            with patch.object(registry, "_running_executable", return_value=None), \
                 patch.object(registry, "_registry_app_path", return_value=None):
                result = registry.diagnose("browser")
            self.assertTrue(result["launchable"])
            self.assertEqual(result["selected_target"], str(exe))
            self.assertEqual(result["selected_method"], "path_candidate")


if __name__ == "__main__":
    unittest.main()
