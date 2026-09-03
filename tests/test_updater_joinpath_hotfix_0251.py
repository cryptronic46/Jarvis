from pathlib import Path
import re
import unittest


class UpdaterJoinPathHotfix0251Tests(unittest.TestCase):
    def test_updater_does_not_pass_multiple_child_paths_to_join_path(self):
        text = Path("update_core.ps1").read_text(encoding="utf-8-sig")
        bad = re.compile(
            r'Join-Path\s+\$Destination\s+"jarvis_core\\services\\wakeword\.py"\s*,\s*'
            r'"jarvis_core\\services\\voice_engine_v2\.py"',
            re.IGNORECASE | re.MULTILINE,
        )
        self.assertIsNone(bad.search(text))

    def test_wake_and_voice_v2_are_loaded_as_separate_paths(self):
        text = Path("update_core.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('(Join-Path $Destination "jarvis_core\\services\\wakeword.py")', text)
        self.assertIn('(Join-Path $Destination "jarvis_core\\services\\voice_engine_v2.py")', text)
        self.assertIn('"`n" +', text)


if __name__ == "__main__":
    unittest.main()
