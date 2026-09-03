import json
import re
import unittest
from pathlib import Path


class ReleaseUpdaterContractTests(unittest.TestCase):
    def test_updater_mirrors_release_trees_and_preserves_runtime(self):
        text = Path("update_core.ps1").read_text(encoding="utf-8")
        self.assertIn('Mirror-Tree "jarvis_core"', text)
        self.assertIn('Mirror-Tree "tests"', text)
        self.assertIn('Mirror-Tree "defaults"', text)
        self.assertIn("/MIR", text)

        for preserved in (
            "memory\\",
            "knowledge\\",
            ".venv\\",
            ".cache\\",
            "logs\\",
            "voice_profiles\\",
            "models\\",
            "skills\\",
            "settings.json",
            "apps.json",
        ):
            self.assertIn(preserved, text)

    def test_updater_validates_full_release(self):
        text = Path("update_core.ps1").read_text(encoding="utf-8")
        self.assertIn("0\\.27\\.8", text)
        self.assertIn("/cyber inspect network", text)
        self.assertIn("/cyber lab status", text)
        self.assertIn("cyber_range.py", text)
        self.assertIn("request_intent.py", text)
        self.assertIn("kali_bridge.py", text)
        self.assertIn("companion_presence.py", text)
        self.assertIn("/cyber kali status", text)
        self.assertIn("/companion status", text)
        self.assertIn("jarvis_core\\skills\\manager.py", text)
        self.assertIn("task_planner.py", text)
        self.assertIn("setup_vision.ps1", text)
        self.assertIn("/skills status", text)
        self.assertIn("/planner status", text)
        self.assertIn("/vision status", text)
        self.assertIn("/guardian status", text)
        self.assertIn("/purple status", text)
        self.assertIn("/listening status", text)
        self.assertIn("/listening recover", text)
        self.assertIn("listening_watchdog.py", text)
        self.assertIn("/vram status", text)
        self.assertIn("/voice latency", text)
        self.assertIn("openwakeword_compat.py", text)
        self.assertIn("--no-deps", text)
        self.assertIn("severity_counts", text)
        self.assertIn("release_all_models", text)
        self.assertIn("/mind status", text)
        self.assertIn("bargein-v2\\+whisper", text)
        self.assertIn("Get-FileHash", text)
        self.assertIn("release_manifest.json", text)
        self.assertIn("Manifest.files", text)
        self.assertIn("bloqueio estrutural de IA externa", text)
        self.assertIn("External AI: HARD BLOCKED", text)
        self.assertIn("Foi encontrado o contrato legacy de autorizacao de especialista externo", text)

    def test_installed_version_check_matches_manifest_and_package_version(self):
        manifest = json.loads(
            Path("release_manifest.json").read_text(encoding="utf-8")
        )
        release = manifest["release"]
        init_text = Path("jarvis_core/__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), release)

        updater = Path("update_core.ps1").read_text(encoding="utf-8")
        expected_regex = release.replace(".", r"\.")
        self.assertIn(
            "if ($VersionText -notmatch '" + expected_regex + "') {",
            updater,
        )
        fail_text = f'Fail "A versao instalada nao e {release}."'
        self.assertIn(fail_text, updater)

    def test_verifier_checks_manifest_and_unexpected_python(self):
        text = Path("verify_release.ps1").read_text(encoding="utf-8")
        self.assertIn("0.27.8", text)
        self.assertIn("Get-FileHash", text)
        self.assertIn("UnexpectedPy", text)
        self.assertIn('Filter "*.py"', text)


if __name__ == "__main__":
    unittest.main()
