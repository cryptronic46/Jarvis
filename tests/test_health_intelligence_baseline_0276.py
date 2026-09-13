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
    def test_local_pc_voice_runtime_is_physically_retired(self):
        s = Settings()

        self.assertFalse(
            s.local_voice_enabled
        )

        cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")

        for retired in (
            "voice_engine_state",
            "microphone.preload_stt()",
            "speaker.ensure_ready()",
            "wake.start()",
            "listening_watchdog.start()",
        ):
            self.assertNotIn(
                retired,
                cli,
            )

    def test_full_validation_never_opens_retired_local_voice(self):
        text = Path(
            'jarvis_core/services/full_validation.py'
        ).read_text(encoding='utf-8')

        self.assertIn(
            'validate_local_voice_retired',
            text,
        )

        for marker in (
            'local_voice_enabled',
            'microphone_opened=False',
            'stt_started=False',
            'wakeword_started=False',
            'audio_playback_started=False',
        ):
            self.assertIn(marker, text)

        for forbidden in (
            'from jarvis_core.services.listening import',
            'from jarvis_core.services.voice_engine_v2 import',
            'from jarvis_core.services.speaker_verification import',
            'from jarvis_core.services.voice_pipeline import',
            'MicrophoneService(',
            'VoiceEngineV2(',
            'SpeakerVerifier(',
            'voice.probe_live_input(',
            'microphone.preload_stt(',
            'import sounddevice',
            'import pyaudiowpatch',
        ):
            self.assertNotIn(
                forbidden,
                text,
            )

    def test_cli_no_longer_bootstraps_local_speaker_lock(self):
        text = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "speaker.ensure_ready()",
            text,
        )
        self.assertNotIn(
            "speaker.set_enabled(False)",
            text,
        )
        self.assertNotIn(
            "SPEAKER_LOCK_AUTO_DISABLED",
            text,
        )
        self.assertNotIn(
            "DisabledSpeakerVerifier",
            text,
        )

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


    def test_log_rotation_caps_exist(self):
        events = Path("jarvis_core/core/events.py").read_text(encoding="utf-8")
        self.assertIn("_rotate_if_needed", events)
        self.assertIn("backup_count", events)

    def test_complexity_alone_does_not_send_cloud(self):
        s=Settings(); s.external_ai_complex_only=True; s.external_ai_complexity_threshold=4
        local=Local('Resposta local substantiva e completa para o pedido complexo.')
        brain=HybridBrain(s, Events(), local)
        q=('Faz uma auditoria completa desta arquitetura complexa, analisa profundamente os trade-offs, '
           'refatora tudo e apresenta um plano detalhado multi-etapa com alternativas. ')*6
        result=brain.ask(q)
        self.assertEqual('LOCAL', result.route)

    def test_complexity_plus_actual_local_insufficiency_stays_local(self):
        s=Settings(); s.external_ai_complex_only=True; s.external_ai_complexity_threshold=4
        local=Local('Não tenho informação suficiente para concluir.')
        brain=HybridBrain(s, Events(), local)
        q=('Faz uma auditoria completa desta arquitetura complexa, analisa profundamente os trade-offs, '
           'refatora tudo e apresenta um plano detalhado multi-etapa com alternativas. ')*6
        result=brain.ask(q)
        self.assertEqual('LOCAL', result.route)

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
        for name in ('requirements.txt','requirements-cloud.txt'):
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
