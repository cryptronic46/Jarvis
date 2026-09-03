import json
import unittest
from pathlib import Path


MUTABLE = {
    "settings.json",
    "apps.json",
    "release_manifest.json",
}

CONTROLLED_TREES = (
    "jarvis_core",
    "tests",
    "defaults",
)

CONTROLLED_TOP_LEVEL = {
    ".gitignore",
    "jarvis.py",
    "setup.ps1",
    "run.ps1",
    "migrate_state.ps1",
    "migrate_to_g.ps1",
    "finalize_g_migration.ps1",
    "diagnose_app_control.ps1",
    "repair_security_baseline.ps1",
    "full_system_validation.ps1",
    "setup_native_brain.ps1",
    "setup_appcontrol_trust.ps1",
    "setup_cloud.ps1",
    "setup_voiceid.ps1",
    "setup_wakeword.ps1",
    "setup_voice_v2.ps1",
    "setup_voice_reset.ps1",
    "install_custom_wake_model.ps1",
    "setup_wake_learning_wsl.ps1",
    "setup_voice_learning.ps1",
    "collect_voice_learning.ps1",
    "train_voice_learning.ps1",
    "setup_vision.ps1",
    "requirements.txt",
    "requirements-cloud.txt",
    "requirements-voiceid.txt",
    "requirements-wakeword.txt",
    "requirements-voice-v2.txt",
    "requirements-voice-learning.txt",
    "README.md",
    "AUDIT_0.27.8.md",
    "acceptance_real_machine.ps1",
    "update_core.ps1",
    "verify_release.ps1",
    "repair_startup_shortcut.ps1",
    "HOTFIX_0.27.8_PERFORMANCE_AUTONOMY_V11.md",
}

RUNTIME_PARTS = {
    "__pycache__",
    ".venv",
    "memory",
    "knowledge",
    ".cache",
    "logs",
    "voice_profiles",
    "models",
}


class ReleaseManifestCompletenessTests(unittest.TestCase):
    def test_manifest_covers_entire_immutable_core_release(self):
        root = Path(".")
        expected = set()

        # Only trees owned by JARVIS Core belong to the immutable
        # release contract. External add-ons under C:\JARVIS are not
        # part of this release and must not be pulled into the manifest.
        for tree_name in CONTROLLED_TREES:
            tree = root / tree_name
            self.assertTrue(
                tree.exists(),
                f"Controlled tree missing: {tree_name}",
            )

            for path in tree.rglob("*"):
                if not path.is_file():
                    continue

                rel = path.relative_to(root)
                if any(
                    part in RUNTIME_PARTS
                    for part in rel.parts
                ):
                    continue

                expected.add(rel.as_posix())

        for name in CONTROLLED_TOP_LEVEL:
            path = root / name
            self.assertTrue(
                path.is_file(),
                f"Controlled top-level file missing: {name}",
            )
            expected.add(name)

        manifest = json.loads(
            Path("release_manifest.json").read_text(
                encoding="utf-8"
            )
        )

        actual = {
            str(item["path"]).replace("\\", "/")
            for item in manifest["files"]
        }

        self.assertEqual(
            expected,
            actual,
        )
        self.assertEqual(
            manifest["release"],
            "0.27.8",
        )
        self.assertEqual(
            set(manifest["mutable_files"]),
            {"settings.json", "apps.json"},
        )

    def test_external_addons_are_not_core_manifest_members(self):
        manifest = json.loads(
            Path("release_manifest.json").read_text(
                encoding="utf-8"
            )
        )

        actual = {
            str(item["path"]).replace("\\", "/")
            for item in manifest["files"]
        }

        self.assertFalse(
            any(
                path.startswith("JARVIS_Live_Wallpaper_")
                for path in actual
            )
        )


if __name__ == "__main__":
    unittest.main()
