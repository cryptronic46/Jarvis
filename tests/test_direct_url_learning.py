import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from jarvis_core.services.autonomy import parse_direct_external_learning_order
from jarvis_core.services.local_research import LocalResearchEngine


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append((name, payload))


class DirectUrlLearningTests(unittest.TestCase):
    def test_exact_kali_owner_order_is_deterministic_direct_learning(self):
        result = parse_direct_external_learning_order(
            "Jarvis, visita este site e aprende tudo o que tens a aprender sobre estas ferramentas "
            "https://www.kali.org/tools/, tens a minha autorização"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "direct_external_learning")
        self.assertEqual(result["topic"], "ferramentas Kali Linux")
        self.assertEqual(result["source_url"], "https://www.kali.org/tools/")
        self.assertTrue(result["direct_user_authority"])

    def test_plain_url_question_is_not_learning_authority(self):
        self.assertIsNone(
            parse_direct_external_learning_order(
                "Jarvis, o que é https://www.kali.org/tools/?"
            )
        )

    def test_same_site_children_are_bounded_to_root_path(self):
        urls = LocalResearchEngine._same_site_child_urls(
            "https://www.kali.org/tools/",
            [
                "https://www.kali.org/tools/nmap/",
                "https://www.kali.org/docs/",
                "https://example.org/tools/nmap/",
                "https://www.kali.org/tools/metasploit-framework/#usage",
                "https://www.kali.org/tools/nmap/",
            ],
            2,
        )
        self.assertEqual(
            urls,
            [
                "https://www.kali.org/tools/nmap/",
                "https://www.kali.org/tools/metasploit-framework/",
            ],
        )

    def test_direct_url_research_never_uses_search_provider_and_stays_bounded(self):
        settings = SimpleNamespace(
            local_research_enabled=True,
            local_research_fetch_max_bytes=200000,
            local_research_timeout_seconds=2.0,
            local_research_source_max_chars=5000,
            local_research_direct_source_max_chars=4500,
            local_research_direct_max_pages=2,
            model="qwen-test",
        )
        events = _Events()
        local = Mock()
        local.synthesize_research.return_value = (
            "As ferramentas Kali Linux estão organizadas por categorias e incluem Nmap. [S1] [S2]"
        )
        engine = LocalResearchEngine(settings, events, local)
        engine.search = Mock(side_effect=AssertionError("direct URL must not call a search provider"))

        pages = {
            "https://www.kali.org/tools/": (
                b"<html><title>Kali Tools</title><body>Kali Linux tools categories reconnaissance vulnerability scanning "
                b"<a href='/tools/nmap/'>Nmap</a><a href='/tools/metasploit-framework/'>Metasploit</a>"
                b"<a href='/docs/'>Docs</a><a href='https://example.org/tools/x/'>External</a></body></html>",
                "text/html",
                "https://www.kali.org/tools/",
            ),
            "https://www.kali.org/tools/nmap/": (
                b"<html><title>Nmap Kali Linux</title><body>Kali Linux tools include Nmap for network discovery and security auditing.</body></html>",
                "text/html",
                "https://www.kali.org/tools/nmap/",
            ),
        }

        def fake_get(url, *, max_bytes, timeout):
            if url not in pages:
                raise AssertionError(f"unexpected fetch: {url}")
            return pages[url]

        engine._get = fake_get
        engine._validate_public_url = lambda url: url

        result = engine.research_url(
            "https://www.kali.org/tools/",
            query="Aprende sobre estas ferramentas.",
            topic="ferramentas Kali Linux",
            deep=True,
        )
        self.assertTrue(result.ok)
        self.assertEqual(len(result.sources or []), 2)
        self.assertEqual((result.sources or [])[0]["url"], "https://www.kali.org/tools/")
        self.assertEqual((result.sources or [])[1]["url"], "https://www.kali.org/tools/nmap/")
        local.synthesize_research.assert_called_once()


if __name__ == "__main__":
    unittest.main()
