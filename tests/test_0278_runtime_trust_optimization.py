import json
import os as real_os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from jarvis_core.services import windows_block_audit as wba


class RuntimeTrustOptimization0278Tests(unittest.TestCase):
    def setUp(self):
        self.trust = Path('setup_appcontrol_trust.ps1').read_text(encoding='utf-8-sig')

    def test_configci_hash_rules_are_batched_and_flattened(self):
        self.assertIn("New-CIPolicyRule -Level Hash -DriverFilePath $runtimePaths", self.trust)
        self.assertIn("Regras Hash normalizadas", self.trust)
        self.assertIn("$rawRules | ForEach-Object", self.trust)
        self.assertNotIn("$rules += @(New-CIPolicyRule -Level Hash -DriverFilePath $full)", self.trust)
        self.assertIn("Parameters['DriverFilePath'].ParameterType", self.trust)
        self.assertIn("Parameters['Rules'].ParameterType", self.trust)

    def test_plan_and_audit_reuse_existing_policy_artifacts_by_default(self):
        plan = self.trust.index("if ($Mode -eq 'Plan')")
        audit = self.trust.index("if ($Mode -eq 'Audit')")
        status = self.trust.index("if ($Mode -eq 'Status')")
        self.assertIn("$plan = if ($RebuildPlan) { Build-PolicyArtifacts } else { Load-Plan }", self.trust[plan:audit])
        self.assertIn("$plan = if ($RebuildPlan) { Build-PolicyArtifacts } else { Load-Plan }", self.trust[audit:status])
        self.assertNotIn("if ($Mode -eq 'Enforce')", self.trust)
        self.assertIn("[switch]$RebuildPlan", self.trust)

    def test_status_degrades_cleanly_without_citool_elevation(self):
        status = self.trust[self.trust.index("if ($Mode -eq 'Status')"):]
        self.assertIn("$policies = Try-Get-CiPolicies", status)
        self.assertIn("UNKNOWN (CiTool requer elevacao", status)
        self.assertIn("Probe-LlamaServer -TimeoutSeconds 20", status)
        self.assertIn("timeout after", self.trust)

    def test_startup_cache_accepts_only_clean_reports(self):
        clean = {
            'ok': True,
            'supported': True,
            'active_block_events': [],
            'native_import_failures': [],
            'native_llama_runtime_probe': {'installed': True, 'ok': True},
        }
        self.assertTrue(wba._startup_cache_report_is_safe(clean))
        bad = dict(clean, active_block_events=[{'id': 3077}])
        self.assertFalse(wba._startup_cache_report_is_safe(bad))
        bad = dict(clean, native_import_failures=['ctranslate2'])
        self.assertFalse(wba._startup_cache_report_is_safe(bad))
        bad = dict(clean, native_llama_runtime_probe={'installed': True, 'ok': False})
        self.assertFalse(wba._startup_cache_report_is_safe(bad))

    def test_startup_cache_reuses_clean_unchanged_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'jarvis_core').mkdir()
            (root / 'jarvis_core' / 'x.py').write_text('x=1\n', encoding='utf-8')
            (root / 'runtime' / 'llama.cpp').mkdir(parents=True)
            (root / 'runtime' / 'llama.cpp' / 'llama-server.exe').write_bytes(b'x')
            (root / 'runtime' / 'llama.cpp' / 'llama-server-impl.dll').write_bytes(b'y')
            (root / '.venv' / 'Scripts').mkdir(parents=True)
            (root / '.venv' / 'Scripts' / 'python.exe').write_bytes(b'z')
            (root / 'memory').mkdir()
            report = {
                'ok': True,
                'supported': True,
                'active_block_events': [],
                'native_import_failures': [],
                'native_llama_runtime_probe': {'installed': True, 'ok': True},
                'elapsed_ms': 1234,
            }
            payload = {
                'schema': wba.STARTUP_CACHE_SCHEMA,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'fingerprint': wba._startup_tree_signal(root),
                'report': report,
            }
            cache = root / 'memory' / wba.STARTUP_CACHE_NAME
            cache.write_text(json.dumps(payload), encoding='utf-8')
            class _OSProxy:
                name = 'nt'
                def __getattr__(self, name):
                    return getattr(real_os, name)
            with patch.object(wba, 'os', _OSProxy()):
                loaded = wba._load_startup_cache(root)
            self.assertIsNotNone(loaded)
            self.assertTrue(loaded['startup_cache_hit'])
            self.assertEqual(loaded['full_audit_elapsed_ms'], 1234)


if __name__ == '__main__':
    unittest.main()
