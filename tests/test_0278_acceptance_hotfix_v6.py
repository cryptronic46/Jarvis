import unittest
from pathlib import Path


class AcceptanceHotfixV6Tests(unittest.TestCase):
    def test_setup_vision_settings_helper_is_project_import_independent(self):
        text = Path("setup_vision.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("JARVIS_VISION_ROOT", text)
        self.assertIn("import json", text)
        self.assertIn("os.replace(tmp, path)", text)
        self.assertNotIn("from jarvis_core.core.config import Settings", text)
        self.assertNotIn("Settings.update_file_values", text)

    def test_modular_vision_fixture_is_hermetic_from_installed_models(self):
        text = Path("tests/test_modular_skills_023.py").read_text(encoding="utf-8")
        self.assertIn('vision_native_model_path=str(root / "missing-vision.gguf")', text)
        self.assertIn('vision_native_mmproj_path=str(root / "missing-mmproj.gguf")', text)
        self.assertIn('native_llama_server_path=str(root / "missing-llama-server.exe")', text)

    def test_settings_helper_payload_is_valid_stdlib_python(self):
        # Extract the literal helper body and compile it. This catches the quoting
        # class of bugs that previously only surfaced in Windows PowerShell.
        text = Path("setup_vision.ps1").read_text(encoding="utf-8-sig")
        marker = "$SettingsCode = @'\n"
        start = text.index(marker) + len(marker)
        end = text.index("\n'@", start)
        body = text[start:end]
        compile(body, "jarvis_vision_settings_helper.py", "exec")


if __name__ == "__main__":
    unittest.main()
