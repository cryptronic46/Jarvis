import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

from jarvis_core.services.openwakeword_compat import sanitize_openwakeword_init


class OpenWakeWordAppControlCompatTests(unittest.TestCase):
    def test_setup_installs_openwakeword_without_training_dependencies(self):
        setup = Path("setup_voice_reset.ps1").read_text(encoding="utf-8")
        req_lines = [
            line.strip().lower()
            for line in Path("requirements-voice-v2.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertIn('--no-deps openwakeword==0.6.0', setup)
        self.assertIn("openwakeword_compat", setup)
        self.assertTrue(any(line.startswith("onnxruntime==") for line in req_lines))
        self.assertTrue(any(line.startswith("pyaudiowpatch==") for line in req_lines))
        self.assertIn("requirements-voice-v2.txt", setup.lower())
        self.assertFalse(any("scikit-learn" in line for line in req_lines))
        self.assertFalse(any("scipy" in line for line in req_lines))

    def test_sanitizer_removes_only_custom_verifier_training_surface(self):
        source = "\n".join([
            "import os",
            "from openwakeword.model import Model",
            "from openwakeword.vad import VAD",
            "from openwakeword.custom_verifier_model import train_custom_verifier",
            "__all__ = ['Model', 'VAD', 'train_custom_verifier']",
            "MODELS = {'hey_jarvis': {'model_path': 'x'}}",
        ])
        cleaned = sanitize_openwakeword_init(source)
        self.assertNotIn("custom_verifier_model", cleaned)
        self.assertNotIn("train_custom_verifier", cleaned)
        self.assertIn("from openwakeword.model import Model", cleaned)
        self.assertIn("from openwakeword.vad import VAD", cleaned)
        self.assertIn("MODELS =", cleaned)
        self.assertIn("__all__ = ['Model', 'VAD']", cleaned)

    def test_compat_loader_does_not_modify_site_packages(self):
        text = Path("jarvis_core/services/openwakeword_compat.py").read_text(encoding="utf-8")
        self.assertIn("No third-party files are modified on disk", text)
        for mutation in ("write_text(", "write_bytes(", "unlink(", "replace("):
            self.assertNotIn(mutation, text)


    def test_loader_skips_a_broken_custom_verifier_module(self):
        from jarvis_core.services import openwakeword_compat as compat

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "openwakeword"
            pkg.mkdir()
            (pkg / "__init__.py").write_text(
                "\n".join([
                    "from openwakeword.model import Model",
                    "from openwakeword.vad import VAD",
                    "from openwakeword.custom_verifier_model import train_custom_verifier",
                    "__all__ = ['Model', 'VAD', 'train_custom_verifier']",
                    "FEATURE_MODELS = {}",
                    "VAD_MODELS = {}",
                    "MODELS = {}",
                    "model_class_mappings = {}",
                    "def get_pretrained_model_paths(inference_framework='onnx'): return []",
                ]),
                encoding="utf-8",
            )
            (pkg / "model.py").write_text("class Model: pass\n", encoding="utf-8")
            (pkg / "vad.py").write_text("class VAD: pass\n", encoding="utf-8")
            (pkg / "custom_verifier_model.py").write_text(
                "raise RuntimeError('CUSTOM_VERIFIER_MUST_NOT_LOAD')\n",
                encoding="utf-8",
            )

            old_path = list(sys.path)
            old_modules = {
                name: module for name, module in sys.modules.items()
                if name == "openwakeword" or name.startswith("openwakeword.")
            }
            try:
                for name in list(sys.modules):
                    if name == "openwakeword" or name.startswith("openwakeword."):
                        sys.modules.pop(name, None)
                sys.path.insert(0, str(root))
                module = compat.load_openwakeword()
                self.assertTrue(module.__jarvis_inference_only__)
                self.assertTrue(hasattr(module, "Model"))
                self.assertTrue(hasattr(module, "VAD"))
                self.assertNotIn("openwakeword.custom_verifier_model", sys.modules)
            finally:
                for name in list(sys.modules):
                    if name == "openwakeword" or name.startswith("openwakeword."):
                        sys.modules.pop(name, None)
                sys.modules.update(old_modules)
                sys.path[:] = old_path

    def test_voice_engine_has_no_direct_openwakeword_import(self):
        tree = ast.parse(Path("jarvis_core/services/voice_engine_v2.py").read_text(encoding="utf-8"))
        direct = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                direct.extend(alias.name for alias in node.names if alias.name == "openwakeword")
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("openwakeword"):
                direct.append(node.module)
        self.assertEqual([], direct)

    def test_doctor_reports_inference_compat_probe(self):
        text = Path("jarvis_core/services/voice_engine_v2.py").read_text(encoding="utf-8")
        self.assertIn('"openwakeword_inference"', text)
        self.assertIn('"openwakeword_compat"', text)
        self.assertIn("openwakeword_runtime_probe()", text)


if __name__ == "__main__":
    unittest.main()
