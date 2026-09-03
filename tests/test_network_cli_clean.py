import unittest
from pathlib import Path
class NetworkCliCleanTests(unittest.TestCase):
    def test_device_commands_are_separate(self):
        cli=Path('jarvis_core/cli.py').read_text(encoding='utf-8')
        self.assertIn('if lower == "/network devices":',cli)
        self.assertIn('if lower == "/network devices all":',cli)
        self.assertIn('format_network_devices',cli)
if __name__ == '__main__': unittest.main()
