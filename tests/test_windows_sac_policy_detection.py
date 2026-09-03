import unittest
from pathlib import Path

from jarvis_core.services.windows_block_audit import (
    SMART_APP_CONTROL_POLICY_ID,
    SMART_APP_CONTROL_POLICY_NAME,
    _annotate_block_event,
    _extract_jarvis_paths,
    _extract_policy_id,
    format_startup_preflight,
)


class WindowsSmartAppControlPolicyDetectionTests(unittest.TestCase):
    def _event(self):
        return {
            "id": 3077,
            "classification": "confirmed_block",
            "source": "AppControl/SmartAppControl",
            "message": (
                r"Code Integrity determined that a process "
                r"(\Device\HarddiskVolume3\Users\tiago\AppData\Local\Python\python.exe) "
                r"attempted to load \Device\HarddiskVolume3\JARVIS\.venv\Lib\site-packages\av\codec\context.pyd "
                r"that did not meet the Enterprise signing level requirements or violated code integrity policy "
                r"(Policy ID:{0283ac0f-fff1-49ae-ada1-8a933130cad6})."
            ),
            "properties": [],
            "time_created": "2026-08-30T09:31:25+00:00",
        }

    def test_policy_id_and_device_path_are_extracted(self):
        event = self._event()
        self.assertEqual(_extract_policy_id(event), SMART_APP_CONTROL_POLICY_ID)
        paths = _extract_jarvis_paths(event, Path(r"C:\JARVIS"))
        self.assertEqual(len(paths), 1)
        normalized = paths[0].replace("/", "\\").lower()
        self.assertTrue(normalized.endswith(r"\.venv\lib\site-packages\av\codec\context.pyd"))

    def test_pyav_sac_block_is_marked_mitigated_for_pcm_path(self):
        event = self._event()
        event["paths"] = _extract_jarvis_paths(event, Path(r"C:\JARVIS"))
        event["policy_id"] = _extract_policy_id(event)
        row = _annotate_block_event(event)
        self.assertTrue(row["smart_app_control"])
        self.assertTrue(row["mitigated"])
        self.assertEqual(row["dependency"], "PyAV")
        self.assertEqual(row["source"], f"SmartAppControl/{SMART_APP_CONTROL_POLICY_NAME}")

    def test_mitigated_only_is_review_not_active_block(self):
        report = {
            "ok": True,
            "supported": True,
            "scanned_files": 500,
            "elapsed_ms": 20,
            "motw_counts": {"total": 0, "native": 0, "python": 0, "script": 0},
            "confirmed_block_events": [{"id": 3077, "mitigated": True}],
            "active_block_events": [],
            "mitigated_block_events": [{"id": 3077, "mitigated": True}],
            "integrity_events": [],
            "native_import_failures": [],
        }
        text = format_startup_preflight(report)
        self.assertIn("Windows Block Audit: REVER", text)
        self.assertIn("bloqueios ativos=0", text)
        self.assertIn("mitigados=1", text)
        self.assertNotIn("Windows Block Audit: BLOQUEIO", text)


if __name__ == "__main__":
    unittest.main()
