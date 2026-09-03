import json
import tempfile
import unittest
from pathlib import Path
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

if __name__ == "__main__":
    unittest.main()
