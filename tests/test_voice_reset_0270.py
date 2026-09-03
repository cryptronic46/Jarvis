from pathlib import Path
import unittest

from jarvis_core.services.voice_engine_v2 import VoiceEngineV2, VoiceV2Config

class Events:
    def emit(self,*a,**k): pass

class VoiceReset0270Tests(unittest.TestCase):
    def test_simple_gate_is_vad_plus_keyword(self):
        svc=VoiceEngineV2(Events(),VoiceV2Config(),lambda _c:None,lambda _p:{"ok":True,"text":""})
        self.assertEqual((False,"vad_rejected"),svc._wake_gate(0.9,0.1))
        self.assertEqual((False,"score_rejected"),svc._wake_gate(0.2,0.9))
        self.assertEqual((True,"vad+kws"),svc._wake_gate(0.6,0.9))
    def test_run_loop_has_no_owner_or_verifier_gate(self):
        text=Path("jarvis_core/services/voice_engine_v2.py").read_text(encoding="utf-8")
        run=text.split("def _run(self)",1)[1].split("# ------------------------------------------------------------------\n    # Diagnostics",1)[0]
        self.assertNotIn("_process_owner_wake_frame",run)
        self.assertNotIn("_verifier_score",run)
    def test_reset_setup_removes_abandoned_voice_packages(self):
        text=Path("setup_voice_reset.ps1").read_text(encoding="utf-8").lower()
        for pkg in ("sherpa-onnx","scikit-learn","scipy","openai-whisper","vosk"):
            self.assertIn(pkg,text)
        self.assertIn("openwakeword==0.6.0",text)
        self.assertIn("faster-whisper==1.2.1",text)
        self.assertIn("remove-pythonpackageifpresent -package 'av'",text)
    def test_custom_openwakeword_model_hook_exists(self):
        text=Path("jarvis_core/services/voice_engine_v2.py").read_text(encoding="utf-8")
        self.assertIn("custom_wake_model_path",text)
        self.assertIn("jarvis.onnx",text)
        self.assertTrue(Path("install_custom_wake_model.ps1").is_file())
    def test_stt_command_is_single_pass_beam_one(self):
        text=Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertIn("selected_beam = 1 if (command_profile or wake_profile)",text)
        self.assertIn("exactly one Faster-Whisper decode",text)
    def test_tool_registry_validates_json_schema_arguments(self):
        text=Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        self.assertIn("def _validate_arguments", text)
        self.assertIn("TOOL_ARGUMENT_VALIDATION_ERROR", text)
        self.assertIn("invalid_type", text)

if __name__ == "__main__": unittest.main()
