import unittest
from pathlib import Path


class ListeningEventContractTests(unittest.TestCase):
    def test_listening_started_does_not_reuse_event_name_argument(self):
        text = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertIn('device_name=str(device_info.get("name", device_index))', text)
        self.assertNotIn(
            '"LISTENING_STARTED",\n            device=device_index,\n            name=',
            text,
        )

    def test_cli_reads_device_name(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("event.data.get('device_name')", text)


if __name__ == "__main__":
    unittest.main()
