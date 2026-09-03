import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from jarvis_core.services.cyber_range import CyberRangeManager, set_cyber_range_manager
from jarvis_core.services.kali_bridge import KaliBridgeManager


NMAP_XML = """<?xml version=\"1.0\"?>
<nmaprun><host><status state=\"up\"/><ports>
<port protocol=\"tcp\" portid=\"22\"><state state=\"open\"/><service name=\"ssh\" product=\"OpenSSH\" version=\"9.6\"/></port>
<port protocol=\"tcp\" portid=\"80\"><state state=\"open\"/><service name=\"http\" product=\"Apache httpd\" version=\"2.4\"/></port>
<port protocol=\"tcp\" portid=\"443\"><state state=\"closed\"/></port>
</ports></host></nmaprun>"""


class KaliBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.range = CyberRangeManager(root / "range.json")
        self.assertTrue(self.range.add_lab_scope("192.168.56.0/24", "lab")["ok"])
        set_cyber_range_manager(self.range)
        self.bridge = KaliBridgeManager(
            root / "kali.json",
            known_hosts_path=root / "known_hosts",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_configure_requires_owner_authorized_lab_host(self):
        denied = self.bridge.configure("192.168.1.10", "kali")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"], "KALI_HOST_NOT_AUTHORIZED_LAB")

        external = self.bridge.configure("8.8.8.8", "kali")
        self.assertFalse(external["ok"])

        allowed = self.bridge.configure("192.168.56.2", "kali")
        self.assertTrue(allowed["ok"])
        self.assertEqual(allowed["authority"], "owner_cli")

    def test_invalid_username_is_rejected(self):
        result = self.bridge.configure("192.168.56.2", "kali;rm -rf /")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "INVALID_KALI_USERNAME")

    @patch("jarvis_core.services.kali_bridge.shutil.which", return_value="C:/Windows/System32/OpenSSH/ssh.exe")
    @patch("jarvis_core.services.kali_bridge.subprocess.run")
    def test_nmap_profile_is_fixed_and_parsed(self, run, _which):
        self.assertTrue(self.bridge.configure("192.168.56.2", "kali")["ok"])
        run.return_value = CompletedProcess([], 0, stdout=NMAP_XML, stderr="")

        result = self.bridge.nmap_service_scan("192.168.56.10", [22, 80, 443])

        self.assertTrue(result["ok"])
        self.assertEqual([x["port"] for x in result["open_services"]], [22, 80])
        argv = run.call_args.args[0]
        self.assertIn("/usr/bin/nmap", argv)
        self.assertIn("-sT", argv)
        self.assertIn("-sV", argv)
        self.assertNotIn("--script", argv)
        self.assertNotIn("-O", argv)
        self.assertNotIn("-D", argv)
        self.assertNotIn("-S", argv)

    @patch("jarvis_core.services.kali_bridge.shutil.which", return_value="ssh")
    @patch("jarvis_core.services.kali_bridge.subprocess.run")
    def test_whatweb_does_not_follow_redirects(self, run, _which):
        self.assertTrue(self.bridge.configure("192.168.56.2", "kali")["ok"])
        run.return_value = CompletedProcess([], 0, stdout="Apache[2.4]", stderr="")
        result = self.bridge.whatweb_fingerprint("192.168.56.10", 8080, False)
        self.assertTrue(result["ok"])
        argv = run.call_args.args[0]
        self.assertIn("--follow-redirect=never", argv)
        self.assertIn("--max-redirects=0", argv)
        self.assertIn("--no-cookies", argv)
        self.assertIn("http://192.168.56.10:8080/", argv)

    @patch("jarvis_core.services.kali_bridge.shutil.which", return_value="ssh")
    @patch("jarvis_core.services.kali_bridge.subprocess.run")
    def test_nikto_profile_excludes_high_impact_tuning(self, run, _which):
        self.assertTrue(self.bridge.configure("192.168.56.2", "kali")["ok"])
        run.return_value = CompletedProcess([], 0, stdout="+ Server: Apache", stderr="")
        result = self.bridge.nikto_safe_web_scan("192.168.56.10", 80, False)
        self.assertTrue(result["ok"])
        argv = run.call_args.args[0]
        tuning_index = argv.index("-Tuning")
        self.assertEqual(argv[tuning_index + 1], "123bde")
        self.assertNotIn("-followredirects", argv)
        self.assertNotIn("-evasion", argv)
        self.assertIn("-nointeractive", argv)
        self.assertIn("-nocheck", argv)

    @patch("jarvis_core.services.kali_bridge.shutil.which", return_value="ssh")
    @patch("jarvis_core.services.kali_bridge.subprocess.run")
    def test_target_is_revalidated_at_execution_time(self, run, _which):
        self.assertTrue(self.bridge.configure("192.168.56.2", "kali")["ok"])
        self.assertTrue(self.range.remove_lab_scope("192.168.56.0/24")["ok"])
        result = self.bridge.nmap_service_scan("192.168.56.10", [80])
        self.assertFalse(result["ok"])
        self.assertIn(result["error"], {
            "KALI_HOST_NO_LONGER_AUTHORIZED_LAB",
            "TARGET_NOT_AUTHORIZED_LAB",
        })
        run.assert_not_called()

    def test_no_arbitrary_shell_api_is_exposed(self):
        source = Path("jarvis_core/services/kali_bridge.py").read_text(encoding="utf-8")
        registry = Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn('"run_kali_shell"', registry)
        self.assertNotIn('"execute_kali_command"', registry)
        self.assertNotIn('"configure_kali_bridge"', registry)


if __name__ == "__main__":
    unittest.main()
