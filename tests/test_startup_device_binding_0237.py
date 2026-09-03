from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from jarvis_core.services.listening import ListeningConfig
from jarvis_core.services.wakeword import WakeWordConfig

ROOT = Path(__file__).resolve().parents[1]


class StartupDeviceBinding0237Tests(unittest.TestCase):
    def test_listening_config_accepts_preferred_device_index(self):
        cfg = ListeningConfig(device=23, preferred_device_index=23)
        self.assertEqual(cfg.preferred_device_index, 23)

    def test_wake_config_accepts_preferred_device_index(self):
        cfg = WakeWordConfig(preferred_device_index=23)
        self.assertEqual(cfg.preferred_device_index, 23)

    def test_cli_constructor_keywords_exist_in_config_signatures(self):
        tree = ast.parse((ROOT / "jarvis_core" / "cli.py").read_text(encoding="utf-8"))
        expected = {
            "ListeningConfig": set(inspect.signature(ListeningConfig).parameters),
            "WakeWordConfig": set(inspect.signature(WakeWordConfig).parameters),
        }
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if name not in expected:
                continue
            supplied = {kw.arg for kw in node.keywords if kw.arg is not None}
            unknown = supplied - expected[name]
            self.assertFalse(unknown, f"{name} receives unknown keywords: {sorted(unknown)}")
            checked += 1
        self.assertGreaterEqual(checked, 2)

    def test_cli_binds_persisted_mic_index_to_both_services(self):
        text = (ROOT / "jarvis_core" / "cli.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("preferred_device_index=settings.mic_device"), 2)


if __name__ == "__main__":
    unittest.main()
