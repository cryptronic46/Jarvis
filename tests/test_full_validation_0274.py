from pathlib import Path
import unittest


class FullValidation0274ContractTests(unittest.TestCase):
    def test_full_validation_covers_runtime_without_pc_audio(self):
        text = Path(
            "jarvis_core/services/full_validation.py"
        ).read_text(encoding="utf-8")

        for marker in (
            "local_voice_retired",
            "jarvis_native_local_reasoning",
            "local_first_policy",
            "windows_block_audit",
        ):
            self.assertIn(marker, text)

        for retired in (
            "from jarvis_core.services.listening import",
            "from jarvis_core.services.voice_engine_v2 import",
            "from jarvis_core.services.speaker_verification import",
            "from jarvis_core.services.voice_pipeline import",
            "MicrophoneService(",
            "VoiceEngineV2(",
            "SpeakerVerifier(",
            "voice.probe_live_input(",
            "microphone.preload_stt(",
            "import sounddevice",
            "import pyaudiowpatch",
        ):
            self.assertNotIn(retired, text)

        for contract in (
            "microphone_opened=False",
            "stt_started=False",
            "wakeword_started=False",
            "audio_playback_started=False",
        ):
            self.assertIn(contract, text)

        ps = Path(
            "full_system_validation.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("verify_release.ps1", ps)
        self.assertIn("unittest discover", ps)
        self.assertIn(
            "full_validation_0277.json",
            ps,
        )
        self.assertNotIn(
            "native/audio/STT",
            ps,
        )


if __name__ == "__main__":
    unittest.main()
