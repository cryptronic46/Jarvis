import unittest

from jarvis_core.services.speech_text import prepare_for_speech_chunks


class SpeechChunkingTests(unittest.TestCase):
    def test_long_response_is_chunked_not_truncated(self):
        text = " ".join(
            f"Frase número {i} com informação útil e completa."
            for i in range(1, 90)
        )
        chunks = prepare_for_speech_chunks(text, max_chars=420)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 420 for chunk in chunks))
        joined = " ".join(chunks)
        self.assertIn("Frase número 1", joined)
        self.assertIn("Frase número 89", joined)

    def test_single_oversized_sentence_is_split(self):
        text = "palavra " * 500
        chunks = prepare_for_speech_chunks(text, max_chars=300)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 300 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
