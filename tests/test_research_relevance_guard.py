import json
import unittest
from unittest.mock import patch

from jarvis_core.core.config import Settings
from jarvis_core.services.local_research import (
    LocalResearchEngine,
    LocalResearchFetchError,
    ResearchSource,
)


class DummyEvents:
    def __init__(self):
        self.rows = []

    def emit(self, name, *args, **kwargs):
        self.rows.append((name, args, kwargs))


class DummyBrain:
    def __init__(self):
        self.calls = []

    def synthesize_research(self, **kwargs):
        self.calls.append(kwargs)
        return "Síntese local relevante sobre cibersegurança [S1]."


class ResearchRelevanceGuardTests(unittest.TestCase):
    def make_engine(self):
        return LocalResearchEngine(Settings(), DummyEvents(), DummyBrain())

    def test_direct_json_source_is_parsed_as_bounded_evidence(self):
        engine = self.make_engine()
        engine._get = lambda *args, **kwargs: (b'{"vulnerabilities":[{"cveID":"CVE-2026-0001"}]}', "application/json", "https://example.test/feed.json")
        source, links = engine._fetch_with_links(ResearchSource(title="Feed", url="https://example.test/feed.json"), max_chars=200)
        self.assertIn("CVE-2026-0001", source.text)
        self.assertEqual(links, [])

    def test_direct_cisa_feed_larger_than_html_limit_uses_json_limit(self):
        engine = self.make_engine()
        official_url = (
            "https://www.cisa.gov/sites/default/files/feeds/"
            "known_exploited_vulnerabilities.json"
        )
        vulnerabilities = [{
            "cveID": f"CVE-2099-{index:04d}",
            "vendorProject": "Example Vendor",
            "product": "Example Product",
            "vulnerabilityName": "Example vulnerability",
            "dateAdded": "2099-01-01",
            "shortDescription": "Known exploitation. " + ("x" * 300),
            "requiredAction": "Apply vendor mitigations.",
            "dueDate": "2099-01-22",
            "knownRansomwareCampaignUse": "Unknown",
            "forensicTriage": "Review process creation events.",
            "notes": "https://www.cisa.gov/known-exploited-vulnerabilities",
            "cwes": ["CWE-78"],
        } for index in range(1694)]
        raw = json.dumps({
            "title": "CISA Catalog of Known Exploited Vulnerabilities",
            "catalogVersion": "2026.09.02",
            "dateReleased": "2026-09-02T16:54:39.8321Z",
            "count": 1694,
            "vulnerabilities": vulnerabilities,
        }).encode("utf-8")
        self.assertGreater(len(raw), 524_288)

        class Response:
            headers = {"Content-Type": "application/json; charset=utf-8"}
            requested_bytes = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return official_url

            def read(self, amount):
                self.requested_bytes = amount
                return raw[:amount]

        response = Response()
        opener = type("Opener", (), {"open": lambda self, request, timeout: response})()
        engine._validate_public_url = lambda url: url
        engine.local.synthesize_research = lambda **kwargs: (
            "O catálogo CISA KEV contém vulnerabilidades exploradas conhecidas [S1]."
        )

        with patch(
            "jarvis_core.services.local_research.build_opener",
            return_value=opener,
        ), patch.object(engine, "available", return_value=True):
            result = engine.research_url(
                official_url,
                query="Aprende o catálogo CISA KEV através do feed JSON oficial.",
                topic="catálogo CISA KEV",
                deep=True,
            )

        self.assertTrue(result.ok)
        self.assertEqual(response.requested_bytes, 5_000_001)
        self.assertIn("CISA", (result.sources or [])[0]["title"])

    def test_direct_json_failure_exposes_explicit_reason_code(self):
        engine = self.make_engine()
        engine._validate_public_url = lambda url: url
        with patch.object(engine, "available", return_value=True), patch.object(
            engine,
            "_fetch_with_links",
            side_effect=LocalResearchFetchError("LOCAL_RESEARCH_JSON_INVALID"),
        ):
            result = engine.research_url(
                "https://www.cisa.gov/feed.json",
                query="Aprende o catálogo CISA KEV.",
                topic="catálogo CISA KEV",
            )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "DIRECT_URL_FETCH_FAILED")
        self.assertEqual(result.reason_code, "LOCAL_RESEARCH_JSON_INVALID")
        self.assertIn("LOCAL_RESEARCH_JSON_INVALID", result.text)

    def test_remote_pdf_extension_is_accepted_with_generic_mime(self):
        from io import BytesIO
        from pypdf import PdfWriter
        stream = BytesIO(); writer = PdfWriter(); writer.add_blank_page(width=100, height=100); writer.write(stream)
        engine = self.make_engine()
        engine._get = lambda *args, **kwargs: (stream.getvalue(), "application/octet-stream", "https://example.test/guide.pdf")
        source, links = engine._fetch_with_links(ResearchSource(title="Guide", url="https://example.test/guide.pdf"), max_chars=200)
        self.assertEqual(source.url, "https://example.test/guide.pdf")
        self.assertEqual(links, [])
    def test_cybersecurity_spelling_variants_share_one_anchor(self):
        engine = self.make_engine()
        for text in (
            "Cibersegurança em Portugal",
            "Cybersegurança para empresas",
            "Cybersecurity best practices",
            "Segurança informática e proteção de sistemas",
        ):
            details = engine._relevance_details("cybersegurança", text)
            self.assertTrue(details["ok"], text)
            self.assertIn("ciberseguranca", details["matched"])

    def test_kosovo_content_is_not_relevant_to_cybersecurity(self):
        engine = self.make_engine()
        kosovo = (
            "Kosovo é uma república nos Balcãs. Pristina é a capital. "
            "Os avisos de viagem falam de crime, terrorismo, minas, incêndios, "
            "inundações e segurança dos viajantes."
        )
        details = engine._relevance_details("cybersegurança", kosovo)
        self.assertFalse(details["ok"])
        self.assertNotIn("ciberseguranca", details["matched"])

    def test_search_rejects_unrelated_provider_and_continues(self):
        engine = self.make_engine()
        engine.SEARCH_PROVIDERS = ("bing_rss", "duckduckgo_html")
        unrelated = ResearchSource(
            title="Kosovo travel advice",
            url="https://example.com/kosovo",
            snippet="Travel safety, borders and emergency advice.",
            provider="bing_rss",
        )
        relevant = ResearchSource(
            title="Cybersecurity fundamentals",
            url="https://example.org/cybersecurity",
            snippet="Cybersecurity guidance for systems and networks.",
            provider="duckduckgo_html",
        )
        with patch.object(engine, "available", return_value=True), \
             patch.object(engine, "_search_bing_rss", return_value=[unrelated]) as bing, \
             patch.object(engine, "_search_duckduckgo", return_value=[relevant]) as ddg:
            result = engine.search("cybersegurança", limit=1)

        self.assertTrue(result["ok"])
        self.assertEqual(result["rejected_irrelevant"], 1)
        self.assertEqual(result["results"][0]["title"], "Cybersecurity fundamentals")
        bing.assert_called_once()
        ddg.assert_called_once()

    def test_unrelated_fetched_page_never_reaches_synthesis(self):
        engine = self.make_engine()
        search_source = ResearchSource(
            title="Cybersecurity guidance",
            url="https://example.org/redirected",
            snippet="Cybersecurity guidance",
            provider="bing_rss",
        )
        redirected_kosovo = ResearchSource(
            title="Kosovo travel advice",
            url="https://example.org/kosovo",
            text="Pristina Kosovo tourism travel borders weather emergency numbers.",
            provider="bing_rss",
        )
        search_payload = {
            "ok": True,
            "_objects": [search_source],
            "results": [search_source.public_dict()],
            "errors": [],
        }
        with patch.object(engine, "available", return_value=True), \
             patch.object(engine, "search", return_value=search_payload), \
             patch.object(engine, "fetch", return_value=redirected_kosovo):
            result = engine.research(
                "aprende sobre cybersegurança",
                topic="cybersegurança",
                search_query="cybersegurança",
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "FETCHED_SOURCES_IRRELEVANT")
        self.assertEqual(engine.local.calls, [])
        self.assertIn("não guardei qualquer aprendizagem", result.text)

    def test_relevant_fetched_page_reaches_local_synthesis(self):
        engine = self.make_engine()
        source = ResearchSource(
            title="Cybersecurity guidance",
            url="https://example.org/cybersecurity",
            snippet="Cybersecurity guidance",
            text=(
                "Cybersecurity protects computers, networks, identities and data. "
                "Cybersecurity risk management includes prevention, detection, response and recovery."
            ),
            provider="duckduckgo_html",
        )
        search_payload = {
            "ok": True,
            "_objects": [source],
            "results": [source.public_dict()],
            "errors": [],
        }
        with patch.object(engine, "available", return_value=True), \
             patch.object(engine, "search", return_value=search_payload), \
             patch.object(engine, "fetch", return_value=source):
            result = engine.research(
                "aprende sobre cybersegurança",
                topic="cybersegurança",
                search_query="cybersegurança",
            )

        self.assertTrue(result.ok)
        self.assertEqual(len(engine.local.calls), 1)
        self.assertEqual(engine.local.calls[0]["topic"], "cybersegurança")

    def test_local_synthesis_can_fail_closed_on_semantic_mismatch(self):
        engine = self.make_engine()
        source = ResearchSource(
            title="Cybersecurity guidance",
            url="https://example.org/cybersecurity",
            snippet="Cybersecurity guidance",
            text="Cybersecurity is mentioned here, but the page payload is semantically unusable.",
            provider="duckduckgo_html",
        )
        search_payload = {
            "ok": True,
            "_objects": [source],
            "results": [source.public_dict()],
            "errors": [],
        }
        engine.local.synthesize_research = lambda **kwargs: "[[RESEARCH_RELEVANCE_REJECTED]]"
        with patch.object(engine, "available", return_value=True), \
             patch.object(engine, "search", return_value=search_payload), \
             patch.object(engine, "fetch", return_value=source):
            result = engine.research(
                "aprende sobre cybersegurança",
                topic="cybersegurança",
                search_query="cybersegurança",
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "LOCAL_SYNTHESIS_RELEVANCE_REJECTED")
        self.assertIn("não foi guardada", result.text)


if __name__ == "__main__":
    unittest.main()
