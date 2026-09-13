import tempfile
import unittest
from pathlib import Path
from jarvis_core.core.config import Settings
from jarvis_core.services.autonomy import AutonomyGuardian

class Events:
    def __init__(self): self.rows=[]
    def emit(self, name, **data): self.rows.append((name,data))

class PerformanceAutonomyHotfixV11Tests(unittest.TestCase):

    def test_expired_scope_gets_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings=Settings(autonomy_pending_ttl_seconds=30, autonomy_expired_cooldown_minutes=180)
            g=AutonomyGuardian(settings, Events(), Path(tmp)/'s.json', Path(tmp)/'a.jsonl')
            payload={'topic':'jarvis','query':'x','deep':False}
            first=g.request(capability='external_learning',payload=payload,reason='recurring_topic',description='pesquisar')
            state=g._load(); state['pending'][0]['expires_at']='2000-01-01T00:00:00+00:00'; g._save(state)
            again=g.request(capability='external_learning',payload=payload,reason='recurring_topic',description='pesquisar')
            self.assertTrue(again.get('cooldown'))
            self.assertFalse(again.get('pending'))

    def test_cli_accepts_simple_natural_approval_and_denial(self):
        text=Path('jarvis_core/cli.py').read_text(encoding='utf-8')
        self.assertIn('"sim", "podes", "pode", "autoriza"', text)
        self.assertIn('natural_denial', text)
        self.assertIn('LLM_RESPONSE_READY', text)


    def test_startup_repair_never_creates_autostart(self):
        text = Path(
            "repair_startup_shortcut.ps1"
        ).read_text(
            encoding="utf-8-sig"
        )

        self.assertIn(
            "sem atalho existente; nada foi criado",
            text,
        )
        self.assertNotIn(
            "JARVIS-Wallpaper",
            text,
        )
        self.assertIn(
            "(?![-A-Za-z0-9_])",
            text,
        )
        self.assertLess(
            text.index(
                "Test-Path -LiteralPath $ShortcutPath"
            ),
            text.index(
                "CreateShortcut($ShortcutPath)"
            ),
        )

if __name__=='__main__': unittest.main()
