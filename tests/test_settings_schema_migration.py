import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.core.config import Settings


class SettingsSchemaMigrationTests(unittest.TestCase):

    def test_missing_fields_are_added_without_overwriting_user_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"

            path.write_text(
                json.dumps({
                    "user_name": "Owner",
                    "proactive_enabled": False,
                }),
                encoding="utf-8",
            )

            result = Settings.ensure_file_schema(path)

            data = json.loads(
                path.read_text(encoding="utf-8")
            )

            self.assertTrue(result["ok"])
            self.assertGreater(result["added_count"], 0)
            self.assertEqual(data["user_name"], "Owner")
            self.assertFalse(data["proactive_enabled"])
            self.assertIn("personal_learning_enabled", data)
            self.assertIn("proactive_quiet_start_hour", data)




    def test_live_core_state_settings_migrate_preserving_owner_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            custom_path = str(Path(tmp) / "owner-core-state.json")
            path.write_text(
                json.dumps({
                    "wallpaper_live_state_path": custom_path,
                    "wallpaper_live_interval_seconds": 7.5,
                }),
                encoding="utf-8",
            )

            result = Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            loaded = Settings.load(path)

            self.assertTrue(result["ok"])
            self.assertEqual(result["core_state_migrated_count"], 2)
            self.assertNotIn("wallpaper_live_state_path", data)
            self.assertNotIn("wallpaper_live_interval_seconds", data)
            self.assertEqual(data["core_state_path"], custom_path)
            self.assertEqual(data["core_state_interval_seconds"], 7.5)
            self.assertEqual(loaded.core_state_path, custom_path)
            self.assertEqual(loaded.core_state_interval_seconds, 7.5)

    def test_live_core_state_load_accepts_legacy_alias_without_schema_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            custom_path = str(Path(tmp) / "legacy-owner-state.json")
            path.write_text(
                json.dumps({
                    "wallpaper_live_state_path": custom_path,
                    "wallpaper_live_interval_seconds": 4.25,
                }),
                encoding="utf-8",
            )

            loaded = Settings.load(path)
            raw = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(loaded.core_state_path, custom_path)
            self.assertEqual(loaded.core_state_interval_seconds, 4.25)
            self.assertIn("wallpaper_live_state_path", raw)
            self.assertNotIn("core_state_path", raw)

    def test_retired_desktop_settings_are_purged_selectively(self):
        retired = {
            "desktop_integration_enabled": True,
            "desktop_wallpaper_root": r"C:\JARVIS-Wallpaper",
            "desktop_bridge_auto_start": True,
            "desktop_bridge_port": 8765,
            "desktop_wallpaper_engine_auto_start": True,
            "desktop_wallpaper_engine_path": r"C:\WallpaperEngine\wallpaper64.exe",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"

            path.write_text(
                json.dumps(
                    {
                        "user_name": "Owner",
                        "owner_extension_key": "keep-me",
                        **retired,
                    }
                ),
                encoding="utf-8",
            )

            result = Settings.ensure_file_schema(path)

            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            loaded = Settings.load(path)

            self.assertEqual(
                result["retired_desktop_settings_removed_count"],
                6,
            )

            self.assertEqual(
                set(
                    result[
                        "retired_desktop_settings_removed"
                    ]
                ),
                set(retired),
            )

            for key in retired:
                self.assertNotIn(key, data)
                self.assertFalse(
                    hasattr(loaded, key)
                )

            self.assertEqual(
                data["owner_extension_key"],
                "keep-me",
            )



    def test_retired_companion_flirt_settings_are_purged(
        self,
    ):
        retired = {
            "companion_flirt_enabled": True,
            "companion_flirt_intensity": 0.75,
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"

            path.write_text(
                json.dumps(
                    {
                        "user_name": "Owner",
                        "companion_enabled": False,
                        "companion_temperature": 0.44,
                        "owner_extension_key": "keep-me",
                        **retired,
                    }
                ),
                encoding="utf-8",
            )

            result = (
                Settings.ensure_file_schema(
                    path
                )
            )

            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            loaded = Settings.load(
                path
            )

            self.assertEqual(
                result[
                    "retired_companion_settings_removed_count"
                ],
                2,
            )

            self.assertEqual(
                set(
                    result[
                        "retired_companion_settings_removed"
                    ]
                ),
                set(retired),
            )

            for key in retired:
                self.assertNotIn(
                    key,
                    data,
                )

                self.assertFalse(
                    hasattr(
                        loaded,
                        key,
                    )
                )

            self.assertFalse(
                data[
                    "companion_enabled"
                ]
            )

            self.assertEqual(
                data[
                    "companion_temperature"
                ],
                0.44,
            )

            self.assertEqual(
                data[
                    "owner_extension_key"
                ],
                "keep-me",
            )

    def test_current_release_has_no_retired_companion_flirt_settings(
        self,
    ):
        data = json.loads(
            Path("settings.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertNotIn(
            "companion_flirt_enabled",
            data,
        )

        self.assertNotIn(
            "companion_flirt_intensity",
            data,
        )

    def test_current_release_settings_has_complete_schema(self):
        data = json.loads(
            Path("settings.json").read_text(
                encoding="utf-8"
            )
        )
        expected = set(
            Settings.__dataclass_fields__
        )
        self.assertEqual(
            expected - set(data),
            set(),
        )


    def test_utf8_bom_settings_are_accepted_and_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"

            path.write_text(
                json.dumps({
                    "user_name": "Owner",
                    "proactive_enabled": False,
                }),
                encoding="utf-8-sig",
            )

            self.assertTrue(
                path.read_bytes().startswith(
                    b"\xef\xbb\xbf"
                )
            )

            result = Settings.ensure_file_schema(path)
            loaded = Settings.load(path)

            self.assertTrue(result["ok"])
            self.assertTrue(result["utf8_bom_normalized"])
            self.assertFalse(
                path.read_bytes().startswith(
                    b"\xef\xbb\xbf"
                )
            )
            self.assertEqual(loaded.user_name, "Owner")
            self.assertFalse(loaded.proactive_enabled)


    def test_update_file_values_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"

            path.write_text(
                json.dumps({
                    "proactive_enabled": True,
                }),
                encoding="utf-8-sig",
            )

            result = Settings.update_file_values(
                {"proactive_enabled": False},
                path,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["changed_count"], 1)
            self.assertFalse(
                Settings.load(path).proactive_enabled
            )


if __name__ == "__main__":
    unittest.main()
