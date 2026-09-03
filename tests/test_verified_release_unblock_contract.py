import unittest
from pathlib import Path


class VerifiedReleaseUnblockContractTests(unittest.TestCase):
    def setUp(self):
        self.text = Path(
            "update_core.ps1"
        ).read_text(encoding="utf-8")

    def test_verified_release_unblocks_by_default_with_preserve_opt_out(self):
        self.assertIn(
            "[switch]$UnblockVerifiedRelease",
            self.text,
        )
        self.assertIn(
            "[switch]$PreserveMarkOfTheWeb",
            self.text,
        )
        self.assertIn(
            "if ($PreserveMarkOfTheWeb)",
            self.text,
        )

    def test_unblock_only_iterates_manifest_files(self):
        self.assertIn(
            "function Unblock-VerifiedManifestFiles",
            self.text,
        )
        self.assertIn(
            "foreach ($Item in $Manifest.files)",
            self.text,
        )
        self.assertIn(
            "Unblock-File -LiteralPath $Path",
            self.text,
        )

    def test_source_is_hash_validated_before_unblock_path(self):
        validate = self.text.index(
            "A validar pacote de origem..."
        )
        unblock = self.text.index(
            "function Unblock-VerifiedManifestFiles"
        )
        # Function definition position is irrelevant; invocation must be after
        # destination verification and source preflight.
        invoke = self.text.rindex(
            "Unblock-VerifiedManifestFiles `"
        )
        self.assertLess(validate, invoke)
        self.assertIn(
            'Label "DESTINO-POS-UNBLOCK"',
            self.text,
        )

    def test_unblock_does_not_walk_venv_or_external_addons(self):
        block_start = self.text.index(
            "function Unblock-VerifiedManifestFiles"
        )
        block_end = self.text.index(
            "function Remove-StaleManagedTopLevelFiles",
            block_start,
        )
        block = self.text[
            block_start:block_end
        ]
        self.assertNotIn(
            "Get-ChildItem",
            block,
        )
        self.assertNotIn(
            ".venv",
            block,
        )


if __name__ == "__main__":
    unittest.main()
