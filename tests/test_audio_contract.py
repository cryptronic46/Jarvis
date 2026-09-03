import unittest

from jarvis_core.tools.windows_actions import set_master_volume


class AudioContractTests(unittest.TestCase):
    def test_non_windows_returns_structured_error(self):
        import platform
        if platform.system() != "Windows":
            result = set_master_volume(30)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "WINDOWS_ONLY")


if __name__ == "__main__":
    unittest.main()
