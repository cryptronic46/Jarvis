import unittest
from pathlib import Path


class MaintenanceScriptsAsciiTests(unittest.TestCase):
    def test_update_and_verify_are_ascii_only(self):
        for name in (
            "update_core.ps1",
            "verify_release.ps1",
        ):
            try:
                Path(name).read_bytes().decode("ascii")
            except UnicodeDecodeError as exc:
                self.fail(f"{name} is not ASCII-only: {exc}")


if __name__ == "__main__":
    unittest.main()
