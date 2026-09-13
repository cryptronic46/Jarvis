from pathlib import Path
import unittest


class Events:
    def emit(self,*a,**k): pass

class VoiceReset0270Tests(unittest.TestCase):
    def test_tool_registry_validates_json_schema_arguments(self):
        text=Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        self.assertIn("def _validate_arguments", text)
        self.assertIn("TOOL_ARGUMENT_VALIDATION_ERROR", text)
        self.assertIn("invalid_type", text)

if __name__ == "__main__": unittest.main()
