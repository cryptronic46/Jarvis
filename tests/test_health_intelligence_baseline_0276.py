import json
import unittest
from pathlib import Path

from jarvis_core.core.config import Settings
from jarvis_core.core.hybrid_brain import HybridBrain
from jarvis_core.services.autonomy import parse_direct_external_learning_order
from jarvis_core.services.cyber_range import CyberRangeManager


class Events:
    def __init__(self): self.rows=[]
    def emit(self,*a,**k): self.rows.append((a,k))


class Local:
    def __init__(self, answer): self.answer=answer; self.calls=0
    def ask(self, text): self.calls += 1; return self.answer
    def clear_history(self): pass


class CloudAnswer:
    text='CLOUD'; model='test'; elapsed_ms=1; estimated_usd=0.0


class Cloud:
    def __init__(self): self.calls=0
    def available(self): return True
    def ask(self, *a, **k): self.calls += 1; return CloudAnswer()
    def clear_history(self): pass


class HealthIntelligenceBaseline0276Tests(unittest.TestCase):
    def test_voice_v2_is_cpu_int8_and_no_silent_legacy_fallback(self):
        s=Settings()
        self.assertEqual('v2', s.voice_input_backend)
        self.assertEqual('cpu', s.voice_v2_stt_device)
        cli=Path('jarvis_core/cli.py').read_text(encoding='utf-8')
        self.assertIn('VOICE_V2_UNAVAILABLE_NO_LEGACY_FALLBACK', cli)
        self.assertNotIn('VOICE_V2_FALLBACK_LEGACY', cli)
        reset=Path('setup_voice_reset.ps1').read_text(encoding='utf-8')
        self.assertIn("'voice_v2_stt_device':'cpu'", reset.replace(' ', ''))

    def test_full_validation_uses_runtime_voice_factory(self):
        text=Path('jarvis_core/services/full_validation.py').read_text(encoding='utf-8')
        self.assertIn('listening_config_from_settings(settings, voice_v2=True)', text)
        self.assertIn('voice_v2_config_from_settings(settings)', text)
        self.assertIn('MicrophoneService(', text)
        self.assertIn('VoiceEngineV2(', text)
        self.assertIn('voice.probe_live_input(seconds=0.60)', text)
        self.assertIn('cleanup_callback=microphone.cleanup_capture', text)
        self.assertIn('wake_transcribe_callback=microphone.transcribe_wake_file', text)
        self.assertNotIn('cleanup_callback=microphone.cleanup,', text)
        self.assertIn('finally:', text)
        self.assertIn('voice.stop()', text)
        self.assertNotIn('load_whisper_model_class()', text)

    def test_voice_lock_auto_disables_when_backend_unhealthy(self):
        text=Path('jarvis_core/cli.py').read_text(encoding='utf-8')
        self.assertIn('speaker.ensure_ready()', text)
        self.assertIn('speaker.set_enabled(False)', text)
        self.assertIn('SPEAKER_LOCK_AUTO_DISABLED', text)

    def test_planners_use_real_structured_json_format(self):
        planner=Path('jarvis_core/skills/builtin/task_planner.py').read_text(encoding='utf-8')
        brain=Path('jarvis_core/core/brain.py').read_text(encoding='utf-8')
        self.assertIn('format=PLAN_RESPONSE_SCHEMA', planner)
        self.assertIn('format=COMPANION_DECISION_SCHEMA', brain)
        self.assertNotIn('raw[raw.find("{")', planner)
        self.assertNotIn('raw[raw.find("{")', brain)

    def test_guardian_cooldown_preserves_active_alert_evidence(self):
        text=Path('jarvis_core/skills/builtin/system_guardian.py').read_text(encoding='utf-8')
        for marker in ('notification_state','fingerprint','occurrences','notification_suppressed','SYSTEM_GUARDIAN_ALERT_COOLDOWN'):
            self.assertIn(marker, text)

    def test_log_rotation_and_tts_cache_caps_exist(self):
        events=Path('jarvis_core/core/events.py').read_text(encoding='utf-8')
        speech=Path('jarvis_core/services/speech.py').read_text(encoding='utf-8')
        self.assertIn('_rotate_if_needed', events)
        self.assertIn('backup_count', events)
        self.assertIn('_prune_cache', speech)
        self.assertIn('cache_max_bytes', speech)
        self.assertIn('cache_max_files', speech)

    def test_complexity_alone_does_not_send_cloud(self):
        s=Settings(); s.external_ai_complex_only=True; s.external_ai_complexity_threshold=4
        local=Local('Resposta local substantiva e completa para o pedido complexo.')
        cloud=Cloud()
        brain=HybridBrain(s, Events(), local, cloud_brain=cloud)
        q=('Faz uma auditoria completa desta arquitetura complexa, analisa profundamente os trade-offs, '
           'refatora tudo e apresenta um plano detalhado multi-etapa com alternativas. ')*6
        result=brain.ask(q)
        self.assertEqual('LOCAL', result.route)
        self.assertEqual(0, cloud.calls)

    def test_complexity_plus_actual_local_insufficiency_stays_local(self):
        s=Settings(); s.external_ai_complex_only=True; s.external_ai_complexity_threshold=4
        local=Local('Não tenho informação suficiente para concluir.')
        cloud=Cloud()
        brain=HybridBrain(s, Events(), local, cloud_brain=cloud)
        q=('Faz uma auditoria completa desta arquitetura complexa, analisa profundamente os trade-offs, '
           'refatora tudo e apresenta um plano detalhado multi-etapa com alternativas. ')*6
        result=brain.ask(q)
        self.assertEqual('LOCAL', result.route)
        self.assertEqual(0, cloud.calls)

    def test_cloud_setup_is_retired_and_external_ai_is_hard_blocked(self):
        ps=Path('setup_cloud.ps1').read_text(encoding='utf-8-sig').lower()
        self.assertIn('external ai hard block', ps)
        self.assertNotIn("'external_ai_enabled':true", ps)
        self.assertNotIn("'cloud_enabled':true", ps)
        self.assertNotIn('setup_secret openai', ps)


    def test_search_topic_drops_authorization_clause(self):
        parsed=parse_direct_external_learning_order(
            'Tens a minha autorização para pesquisares na internet e aprenderes sobre baterias de estado sólido'
        )
        self.assertIsNotNone(parsed)
        self.assertEqual('baterias de estado sólido', parsed['topic'])
        self.assertNotIn('autoriz', parsed['query'].lower())

    def test_tool_json_schema_checks_nested_constraints(self):
        text=Path('jarvis_core/core/tool_registry.py').read_text(encoding='utf-8')
        self.assertIn('Draft202012Validator', text)
        self.assertIn('check_schema(params)', text)
        self.assertIn('additionalProperties', text)
        self.assertIn('def validate_arguments', text)

    def test_owner_machine_defensive_is_separate_scope(self):
        mgr=CyberRangeManager(enabled=True)
        decision=mgr.classify('127.0.0.1')
        self.assertEqual('OWNER_MACHINE', decision['scope'])
        self.assertFalse(decision['authorized'])
        kali=Path('jarvis_core/services/kali_bridge.py').read_text(encoding='utf-8')
        self.assertIn('OWNER_MACHINE_DEFENSIVE', kali)
        self.assertIn('_owner_defensive_target_decision', kali)

    def test_dependencies_are_exactly_pinned(self):
        for name in ('requirements.txt','requirements-cloud.txt','requirements-voice-v2.txt','requirements-voiceid.txt','requirements-voice-learning.txt'):
            for raw in Path(name).read_text(encoding='utf-8').splitlines():
                line=raw.strip()
                if not line or line.startswith('#'): continue
                self.assertIn('==', line, f'{name}: not pinned: {line}')

    def test_quit_contract_checks_native_runtime_process(self):
        run=Path('run.ps1').read_text(encoding='utf-8')
        accept=Path('acceptance_real_machine.ps1').read_text(encoding='utf-8')
        self.assertIn('Stop-JarvisNativeBrain', run)
        self.assertIn('@("/quit") | & .\\run.ps1', accept)
        self.assertIn('native_llama_runtime.json', accept)
        self.assertIn('native_llama_still_resident', accept)

    def test_utf8_pt_pt_baseline(self):
        jarvis=Path('jarvis.py').read_text(encoding='utf-8')
        run=Path('run.ps1').read_text(encoding='utf-8')
        self.assertIn('SetConsoleOutputCP(65001)', jarvis)
        self.assertIn('PYTHONIOENCODING', run)
        probe='ã ç á é ó € — “ ”'
        self.assertEqual(probe, probe.encode('utf-8').decode('utf-8'))

    def test_windows_powershell_51_encoding_contract(self):
        acceptance = Path('acceptance_real_machine.ps1').read_bytes()
        self.assertTrue(all(byte < 128 for byte in acceptance),
                        'acceptance_real_machine.ps1 must stay ASCII-safe before the encoding gate runs')
        acceptance_text = acceptance.decode('ascii')
        self.assertIn('$env:PYTHONIOENCODING = "utf-8"', acceptance_text)
        self.assertIn('[char]0x00E3', acceptance_text)
        self.assertIn('[char]0x201C', acceptance_text)
        updater = Path('update_core.ps1').read_text(encoding='utf-8')
        self.assertIn('Repair-ExternalPowerShell51Encoding', updater)
        self.assertIn('JARVIS_Live_Wallpaper_0.1.0\\install.ps1', updater)

        # Only release-controlled PowerShell belongs to the Core encoding gate.
        # External add-ons are deliberately preserved outside the Core manifest
        # and must never make a Core update/setup fail.
        manifest = json.loads(Path('release_manifest.json').read_text(encoding='utf-8'))
        controlled_ps1 = [
            Path(item['path'])
            for item in manifest['files']
            if item['path'].lower().endswith('.ps1')
        ]
        self.assertTrue(controlled_ps1, 'release manifest contains no controlled PowerShell scripts')
        for ps1 in controlled_ps1:
            raw = ps1.read_bytes()
            if any(byte >= 128 for byte in raw):
                self.assertTrue(
                    raw.startswith(b'\xef\xbb\xbf'),
                    f'{ps1} contains non-ASCII text but has no UTF-8 BOM for Windows PowerShell 5.1',
                )


if __name__ == '__main__':
    unittest.main()
