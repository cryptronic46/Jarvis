import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BRIDGE = Path(__file__).parents[1] / "bridge" / "jarvis_bridge.py"
spec = importlib.util.spec_from_file_location("jarvis_wallpaper_bridge", BRIDGE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def test_bind_policy_is_loopback_in_main_source(self):
        text = BRIDGE.read_text(encoding="utf-8")
        self.assertIn('"127.0.0.1"', text)
        self.assertIn("loopback/localhost", text)

    def test_security_reads_baseline_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Path(tmp)
            (core / "memory").mkdir()
            (core / "memory" / "security_baseline.json").write_text(
                json.dumps({
                    "created_at": "2026-08-28T15:01:03+01:00",
                    "fingerprint": {
                        "firewall_all_enabled": True,
                        "defender_realtime_enabled": True,
                        "rdp_enabled": False,
                        "remote_assistance_enabled": False,
                    },
                }),
                encoding="utf-8",
            )
            (core / "memory" / "security_watch.json").write_text(
                json.dumps({
                    "checked_at": "2026-08-28T15:02:00+01:00",
                    "alerts": [],
                }),
                encoding="utf-8",
            )
            result = bridge.get_security(core)
            self.assertTrue(result["baseline_exists"])
            self.assertTrue(result["firewall_all_enabled"])
            self.assertEqual(result["alerts"], [])

    def test_agenda_filters_completed_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Path(tmp)
            (core / "memory").mkdir()
            (core / "memory" / "agenda.json").write_text(
                json.dumps({
                    "items": [
                        {"title": "Done", "done": True},
                        {"title": "Pending", "done": False, "when": None},
                    ]
                }),
                encoding="utf-8",
            )
            result = bridge.get_agenda(core)
            self.assertEqual(result["pending_count"], 1)
            self.assertEqual(result["upcoming"][0]["title"], "Pending")

    def test_state_offline_when_core_not_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(bridge, "core_process_running", return_value=False):
                result = bridge.derive_state(Path(tmp))
            self.assertEqual(result["name"], "OFFLINE")

    def test_state_machine_reads_speaking_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Path(tmp)
            (core / "logs").mkdir()
            events = [
                {
                    "name": "WAKE_WORD_DETECTED",
                    "timestamp": "2026-08-28T18:00:00+01:00",
                    "data": {},
                },
                {
                    "name": "THINKING_STARTED",
                    "timestamp": "2026-08-28T18:00:01+01:00",
                    "data": {},
                },
                {
                    "name": "SPEECH_STARTED",
                    "timestamp": "2026-08-28T18:00:02+01:00",
                    "data": {},
                },
            ]
            (core / "logs" / "events.jsonl").write_text(
                "\n".join(json.dumps(x) for x in events),
                encoding="utf-8",
            )
            with patch.object(bridge, "core_process_running", return_value=True):
                result = bridge.derive_state(core)
            self.assertEqual(result["name"], "SPEAKING")


if __name__ == "__main__":
    unittest.main()
