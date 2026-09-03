import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from jarvis_core.services.autonomy import parse_direct_external_learning_order
from jarvis_core.services.local_research import LocalResearchEngine


class _Events:
    def emit(self, name, **payload):
        pass


class AcceptanceHotfixV4Tests(unittest.TestCase):
    def test_direct_url_preserves_actual_owner_question_as_query(self):
        raw = "Estuda https://www.python.org/downloads/ e diz-me qual é a versão atual do Python."
        parsed = parse_direct_external_learning_order(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["query"], raw)
        self.assertEqual(parsed["topic"], "a versão atual do Python")

    def test_direct_url_synthesis_receives_owner_selected_url_context(self):
        settings = SimpleNamespace(
            local_research_enabled=True,
            local_research_fetch_max_bytes=200000,
            local_research_timeout_seconds=2.0,
            local_research_source_max_chars=5000,
            local_research_direct_source_max_chars=4500,
            local_research_direct_max_pages=1,
            model="qwen-test",
        )
        local = Mock()
        local.synthesize_research.return_value = "A versão atual indicada é Python 3.x. [S1]"
        engine = LocalResearchEngine(settings, _Events(), local)
        engine._validate_public_url = lambda url: url
        engine._get = lambda url, *, max_bytes, timeout: (
            b"<html><title>Python Downloads</title><body>Download the latest Python 3 release and installers.</body></html>",
            "text/html",
            "https://www.python.org/downloads/",
        )
        result = engine.research_url(
            "https://www.python.org/downloads/",
            query="Estuda https://www.python.org/downloads/ e diz-me qual é a versão atual do Python.",
            topic="a versão atual do Python",
            deep=False,
        )
        self.assertTrue(result.ok)
        kwargs = local.synthesize_research.call_args.kwargs
        self.assertEqual(kwargs["owner_selected_url"], "https://www.python.org/downloads/")
        self.assertTrue(kwargs["relevance_preverified"])

    def test_setup_vision_executes_temp_python_file_not_inline_c_code(self):
        text = Path("setup_vision.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("jarvis_vision_download_", text)
        self.assertIn("WriteAllText($DownloadHelper", text)
        self.assertIn("& $Python $DownloadHelper", text)
        self.assertNotIn("& $Python -c $DownloadCode", text)
        self.assertIn('print("[JARVIS/VISION] downloaded: " + str(path))', text)

    def test_setup_vision_cleans_temp_helper(self):
        text = Path("setup_vision.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("finally", text)
        self.assertIn("Remove-Item -LiteralPath $DownloadHelper", text)


if __name__ == "__main__":
    unittest.main()
