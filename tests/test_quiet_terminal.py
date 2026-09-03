import json
import unittest
from pathlib import Path


class QuietTerminalTests(unittest.TestCase):
    def setUp(self):
        self.cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.config = Path(
            "jarvis_core/core/config.py"
        ).read_text(encoding="utf-8")
        self.settings = json.loads(
            Path("settings.json").read_text(encoding="utf-8")
        )

    def test_quiet_mode_is_default_even_for_legacy_settings(self):
        self.assertIn("show_events: bool = False", self.config)
        self.assertFalse(self.settings["show_events"])
        self.assertIn('debug_terminal = {"enabled": False}', self.cli)

    def test_runtime_event_gate_exists(self):
        self.assertIn("def terminal_event_printer(event: Event)", self.cli)
        self.assertIn('if debug_terminal["enabled"]:', self.cli)
        self.assertIn("events.subscribe(terminal_event_printer)", self.cli)

    def test_debug_commands_exist(self):
        for command in ("/debug on", "/debug off", "/debug status"):
            self.assertIn(f'lower == "{command}"', self.cli)

    def test_perf_output_is_conditioned_on_debug(self):
        # All three PERF print sites should now have a nearby debug gate.
        self.assertEqual(self.cli.count("[PERF  ]"), 3)
        self.assertGreaterEqual(
            self.cli.count('if debug_terminal["enabled"]:'),
            5,
        )

    def test_eventbus_still_persists_diagnostics(self):
        events = Path(
            "jarvis_core/core/events.py"
        ).read_text(encoding="utf-8")
        self.assertIn('self.event_log = self.log_dir / "events.jsonl"', events)
        self.assertIn("self.event_log.open", events)


if __name__ == "__main__":
    unittest.main()
