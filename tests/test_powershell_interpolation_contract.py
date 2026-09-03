import re
import unittest
from pathlib import Path


VALID_SCOPES = {
    "env",
    "global",
    "script",
    "local",
    "private",
    "using",
}


class PowerShellInterpolationContractTests(unittest.TestCase):
    def test_no_ambiguous_variable_colon_in_double_quoted_strings(self):
        violations = []
        pattern = re.compile(
            r'"[^"\r\n]*\$([A-Za-z_][A-Za-z0-9_]*):'
        )

        for path in sorted(Path(".").glob("*.ps1")):
            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            for line_no, line in enumerate(
                text.splitlines(),
                start=1,
            ):
                for match in pattern.finditer(line):
                    name = match.group(1).lower()
                    if name in VALID_SCOPES:
                        continue
                    violations.append(
                        f"{path}:{line_no}:${match.group(1)}:"
                    )

        self.assertEqual([], violations)

    def test_updater_uses_braced_label(self):
        text = Path(
            "update_core.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('"${Label}:', text)
        self.assertNotIn('"$Label:', text)

    def test_verifier_uses_braced_version_before_colon(self):
        text = Path(
            "verify_release.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"JARVIS Core ${ExpectedVersion}: OK"',
            text,
        )


if __name__ == "__main__":
    unittest.main()
