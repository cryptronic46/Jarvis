import unittest
from jarvis_core.services.speech_text import prepare_for_speech


class SpeechTextTests(unittest.TestCase):
    def test_removes_markdown_and_url(self):
        src = "**GPU:** 48°C. Ver [fonte](https://example.com)."
        result = prepare_for_speech(src)
        self.assertNotIn("**", result)
        self.assertNotIn("https://", result)
        self.assertIn("48 graus Celsius", result)

    def test_does_not_read_code_block(self):
        src = "Resultado. ```powershell\nGet-Process\n``` Concluído."
        result = prepare_for_speech(src)
        self.assertNotIn("Get-Process", result)
        self.assertIn("Resultado", result)


if __name__ == "__main__":
    unittest.main()
