import unittest
from pathlib import Path

from jarvis_core.services.listening import ListeningConfig, MicrophoneService


class DummyEvents:
    def emit(self, *args, **kwargs):
        pass


class FakeModel:
    def transcribe(
        self,
        path,
        language=None,
        beam_size=None,
        vad_filter=None,
        condition_on_previous_text=None,
        temperature=None,
        without_timestamps=None,
        initial_prompt=None,
        hotwords=None,
    ):
        return [], type(
            "Info",
            (),
            {"language": "pt", "language_probability": 1.0},
        )()


class OldFakeModel:
    def transcribe(
        self,
        path,
        language=None,
        beam_size=None,
        vad_filter=None,
        condition_on_previous_text=None,
        temperature=None,
        without_timestamps=None,
    ):
        return [], type(
            "Info",
            (),
            {"language": "pt", "language_probability": 1.0},
        )()


class SttCommandAccuracyProfileTests(unittest.TestCase):
    def make_service(self):
        return MicrophoneService(DummyEvents(), ListeningConfig())

    def test_command_profile_uses_greedy_beam_one(self):
        kwargs = self.make_service()._transcribe_kwargs(FakeModel(), "command")
        self.assertEqual(kwargs["beam_size"], 1)

    def test_prompt_and_hotwords_are_used_when_supported(self):
        kwargs = self.make_service()._transcribe_kwargs(FakeModel(), "command")
        self.assertIn("initial_prompt", kwargs)
        self.assertIn("hotwords", kwargs)
        self.assertIn("Jarvis", kwargs["initial_prompt"])
        self.assertIn("Brave", kwargs["hotwords"])

    def test_older_versions_do_not_receive_unsupported_options(self):
        kwargs = self.make_service()._transcribe_kwargs(OldFakeModel(), "command")
        self.assertNotIn("initial_prompt", kwargs)
        self.assertNotIn("hotwords", kwargs)
        self.assertEqual(kwargs["beam_size"], 1)

    def test_default_profile_remains_fast(self):
        kwargs = self.make_service()._transcribe_kwargs(FakeModel(), "default")
        self.assertEqual(kwargs["beam_size"], 1)
        self.assertNotIn("initial_prompt", kwargs)
        self.assertNotIn("hotwords", kwargs)

    def test_wake_reuses_command_transcriber(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn(
            "transcribe_callback=microphone.transcribe_command_file",
            cli,
        )


if __name__ == "__main__":
    unittest.main()
