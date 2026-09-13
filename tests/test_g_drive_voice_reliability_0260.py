from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_core.core.config import Settings


class DummyEvents:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class FakeModel:
    last_kwargs = None

    def __init__(self, **kwargs):
        FakeModel.last_kwargs = dict(kwargs)
        self.models = {}
        self.model_inputs = {}
        self.prediction_buffer = {}


class FakeVad:
    def __init__(self, n_threads=1):
        self.n_threads = n_threads


class GDriveVoiceReliability0260Tests(unittest.TestCase):




    def test_g_migration_does_not_copy_old_venv(self):
        text = Path("migrate_to_g.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'Destination = "G:\\JARVIS"',
            text,
        )
        self.assertIn(
            "Old .venv intentionally not copied",
            text,
        )
        self.assertNotIn("WallpaperDestination", text)
        self.assertNotIn("JARVIS-Wallpaper", text)
        self.assertNotIn("setup_voice_v2.ps1", text)
        self.assertNotIn("voice_profiles", text)

        persistent_block = text.split(
            "foreach ($name in @(",
            1,
        )[1].split(
            "))",
            1,
        )[0]

        self.assertNotIn(
            r"'.venv'",
            persistent_block,
        )

    def test_app_control_doctor_uses_existing_auditor(self):
        text = Path("diagnose_app_control.ps1").read_text(encoding="utf-8")
        self.assertIn("windows_block_audit", text)
        self.assertNotIn("app_control_policy", text)




if __name__ == "__main__":
    unittest.main()
