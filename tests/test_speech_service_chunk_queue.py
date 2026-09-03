import unittest

from jarvis_core.services.speech import SpeechConfig, SpeechService


class Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class SpeechServiceChunkQueueTests(unittest.TestCase):
    def test_say_queues_all_segments_instead_of_truncating(self):
        events = Events()
        service = SpeechService(
            events,
            SpeechConfig(enabled=True, max_chars=220, cache_enabled=False),
        )
        text = " ".join(
            f"Frase {i} contém informação relevante e deve ser falada por completo."
            for i in range(1, 70)
        )
        self.assertTrue(service.say(text))
        self.assertGreater(service._queue.qsize(), 1)
        queued = []
        while not service._queue.empty():
            queued.append(service._queue.get_nowait())
        joined = " ".join(queued)
        self.assertIn("Frase 1", joined)
        self.assertIn("Frase 69", joined)
        event = next(data for name, data in events.rows if name == "SPEECH_QUEUED")
        self.assertEqual(event["chunks"], len(queued))


if __name__ == "__main__":
    unittest.main()
