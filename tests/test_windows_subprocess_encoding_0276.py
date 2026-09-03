import ast
import unittest
from pathlib import Path

from jarvis_core.core.subprocess_text import decode_subprocess_stream
from jarvis_core.services.windows_block_audit import _decode_subprocess_stream


class WindowsSubprocessEncoding0276Tests(unittest.TestCase):
    def test_cp850_portuguese_output_decodes_without_utf8_reader_failure(self):
        expected = "informação primárias: çã áé ó"
        raw = expected.encode("cp850")
        self.assertEqual(decode_subprocess_stream(raw), expected)

    def test_stdlib_windows_block_auditor_exposes_binary_decoder(self):
        expected = "informação primárias: çã áé ó"
        self.assertEqual(_decode_subprocess_stream(expected.encode("cp850")), expected)

    def test_utf8_output_still_decodes_exactly(self):
        expected = "ã ç á é ó € — “ ”"
        self.assertEqual(decode_subprocess_stream(expected.encode("utf-8")), expected)

    def test_mock_or_predecoded_text_is_preserved(self):
        expected = "já decodificado"
        self.assertEqual(decode_subprocess_stream(expected), expected)

    def test_captured_runtime_subprocesses_do_not_enable_text_mode(self):
        root = Path("jarvis_core")
        violations = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if not isinstance(node.func.value, ast.Name) or node.func.value.id != "subprocess":
                    continue
                if node.func.attr not in {"run", "check_output"}:
                    continue
                keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                captures = node.func.attr == "check_output" or (
                    isinstance(keywords.get("capture_output"), ast.Constant)
                    and keywords["capture_output"].value is True
                )
                if not captures:
                    continue
                text_value = keywords.get("text") or keywords.get("universal_newlines")
                if isinstance(text_value, ast.Constant) and text_value.value is True:
                    violations.append(f"{path}:{node.lineno}: text mode")
                if "encoding" in keywords:
                    violations.append(f"{path}:{node.lineno}: explicit encoding")
        self.assertEqual(violations, [], "Captured subprocess output must stay binary: " + "; ".join(violations))


if __name__ == "__main__":
    unittest.main()
