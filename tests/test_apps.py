import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_core.tools.windows_actions import AppRegistry

class AppRegistryTests(unittest.TestCase):
    def test_alias_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "apps.json"
            p.write_text(json.dumps({
                "apps":{"brave":{
                    "name":"Brave",
                    "aliases":["browser"],
                    "launch":{"type":"path","target":"x"},
                    "process_names":["brave.exe"]
                }}
            }), encoding="utf-8")
            reg = AppRegistry(p)
            self.assertEqual(reg.resolve("browser")[0], "brave")
            self.assertIsNone(reg.resolve("random-app"))

    def test_open_is_idempotent_when_registered_process_is_already_running(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "apps.json"
            p.write_text(json.dumps({"apps":{"notepad":{"name":"Bloco de Notas","aliases":["notepad"],"launch":{"type":"command","command":"notepad.exe"},"process_names":["notepad.exe"]}}}), encoding="utf-8")
            reg = AppRegistry(p)
            existing = [{"pid":123,"name":"notepad.exe"}]
            with patch.object(reg, "running", return_value=existing), patch("jarvis_core.tools.windows_actions.subprocess.Popen") as popen:
                result = reg.open("notepad")
            self.assertTrue(result["ok"]); self.assertTrue(result["already_running"]); self.assertTrue(result["effect_verified"])
            popen.assert_not_called()
if __name__ == "__main__":
    unittest.main()
