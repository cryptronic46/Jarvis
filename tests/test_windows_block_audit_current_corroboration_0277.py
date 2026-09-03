import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.windows_block_audit import (
    _corroborate_block_event,
    _norm_path_key,
)


class WindowsBlockAuditCurrentCorroboration0277Tests(unittest.TestCase):
    def _row(self, path=None):
        paths = [] if path is None else [str(path)]
        return {
            "id": 3077,
            "classification": "confirmed_block",
            "source": "AppControl/SmartAppControl",
            "time_created": "2099-01-01T00:00:00+00:00",
            "paths": paths,
            "referenced_paths_existing": paths,
            "referenced_paths_missing": [],
            "resolved_historical": False,
            "mitigated": False,
        }

    def test_event_without_extractable_path_is_historical_review_not_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = _corroborate_block_event(
                self._row(),
                marked_path_keys=set(),
                native_failures=[],
                llama_probe={"installed": True, "ok": True},
                root=Path(tmp),
            )
        self.assertFalse(row["current_block_corroborated"])
        self.assertTrue(row["historical_uncorroborated"])
        self.assertEqual(row["resolution"], "event_has_no_extractable_current_path")

    def test_current_motw_corroborates_present_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "module.dll"
            path.write_bytes(b"x")
            row = _corroborate_block_event(
                self._row(path),
                marked_path_keys={_norm_path_key(path)},
                native_failures=[],
                llama_probe={"installed": False, "ok": True},
                root=Path(tmp),
            )
        self.assertTrue(row["current_block_corroborated"])
        self.assertEqual(row["current_block_reason"], "referenced_artifact_still_has_motw")

    def test_old_llama_block_is_resolved_when_current_runtime_load_probe_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "runtime" / "llama.cpp" / "llama-server.exe"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"MZ")
            row = _corroborate_block_event(
                self._row(path),
                marked_path_keys=set(),
                native_failures=[],
                llama_probe={"installed": True, "ok": True, "returncode": 0},
                root=root,
            )
        self.assertFalse(row["current_block_corroborated"])
        self.assertTrue(row["resolved_historical"])
        self.assertEqual(row["resolution"], "jarvis_llama_runtime_load_probe_now_ok")

    def test_existing_unmarked_event_without_failed_current_probe_is_review_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "some" / "old.dll"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"x")
            row = _corroborate_block_event(
                self._row(path),
                marked_path_keys=set(),
                native_failures=[],
                llama_probe={"installed": True, "ok": True},
                root=root,
            )
        self.assertFalse(row["current_block_corroborated"])
        self.assertTrue(row["historical_uncorroborated"])
        self.assertEqual(row["resolution"], "historical_event_without_present_block_corroboration")


    def test_blocked_standalone_llama_is_mitigated_when_local_executor_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "runtime" / "llama.cpp" / "llama-server.exe"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"MZ")
            row = _corroborate_block_event(
                self._row(path),
                marked_path_keys=set(),
                native_failures=[],
                llama_probe={"installed": True, "ok": False, "returncode_hex": "0xC0E90002"},
                local_executor_probe={"ok": True, "model_ok": True},
                root=root,
            )
        self.assertFalse(row["current_block_corroborated"])
        self.assertTrue(row["mitigated"])
        self.assertEqual(row["effective_executor"], "ollama_local_compat")

    def test_setup_repairs_native_brain_before_security_baseline(self):
        text = Path("setup.ps1").read_text(encoding="utf-8-sig")
        self.assertLess(text.index("setup_native_brain.ps1"), text.index("repair_security_baseline.ps1"))

    def test_security_repair_reports_llm_probe_and_inline_block_details(self):
        text = Path("repair_security_baseline.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("JARVIS_LLM_RUNTIME_CURRENT:", text)
        self.assertIn("Detalhe dos bloqueios atualmente corroborados", text)
        self.assertIn("historical_uncorroborated", text)


if __name__ == "__main__":
    unittest.main()
