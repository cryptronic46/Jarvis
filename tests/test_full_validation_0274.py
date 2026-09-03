from pathlib import Path
import unittest

class FullValidation0274ContractTests(unittest.TestCase):
    def test_full_validation_covers_real_runtime(self):
        text=Path('jarvis_core/services/full_validation.py').read_text(encoding='utf-8')
        for marker in ('native_runtime','voice_runtime_pipeline','MicrophoneService','VoiceEngineV2','jarvis_native_local_reasoning','local_first_policy','windows_block_audit'):
            self.assertIn(marker,text)
        self.assertIn('listening_config_from_settings(settings, voice_v2=True)', text)
        self.assertNotIn('load_whisper_model_class()', text)
        ps=Path('full_system_validation.ps1').read_text(encoding='utf-8')
        self.assertIn('verify_release.ps1',ps)
        self.assertIn('unittest discover',ps)
        self.assertIn('full_validation_0277.json',ps)

if __name__=='__main__': unittest.main()
