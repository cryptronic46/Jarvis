import json
import re
import unittest
from pathlib import Path


class ReleaseInstallerCoverageTests(unittest.TestCase):
    def test_every_manifest_top_level_file_is_installed(self):
        manifest = json.loads(
            Path("release_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        updater = Path(
            "update_core.ps1"
        ).read_text(encoding="utf-8")

        manifest_top_level = {
            str(item["path"]).replace("\\", "/")
            for item in manifest["files"]
            if "/" not in str(item["path"]).replace("\\", "/")
        }

        block = re.search(
            r"\$TopFiles\s*=\s*@\((.*?)\n\s*\)",
            updater,
            re.S,
        )
        self.assertIsNotNone(block)

        installed = set(
            re.findall(
                r'"([^"]+)"',
                block.group(1),
            )
        )

        required = manifest_top_level | {
            "release_manifest.json",
        }

        self.assertEqual(
            required,
            installed,
        )

    def test_update_core_itself_is_installed(self):
        updater = Path(
            "update_core.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"update_core.ps1"',
            updater,
        )

    def test_source_preflight_happens_before_copy(self):
        updater = Path(
            "update_core.ps1"
        ).read_text(encoding="utf-8")

        preflight = updater.index(
            'Write-Host "A validar pacote de origem..."'
        )
        copy = updater.index(
            'Mirror-Tree "jarvis_core"'
        )

        self.assertLess(preflight, copy)
        self.assertIn('-Label "ORIGEM"', updater)
        self.assertIn('-Label "DESTINO"', updater)


if __name__ == "__main__":
    unittest.main()
