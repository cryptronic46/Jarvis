from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.services.action_truth import guard_unverified_local_action_claim
from jarvis_core.services.autonomy import AuthorizedLearningStore
from jarvis_core.services.request_intent import classify_request_intent


class _Events:
    def emit(self, *args, **kwargs):
        return None


class _Apps:
    def list_apps(self):
        return []


class _Tools:
    def __init__(self):
        self.calls = []
        self.request_started_at = None
        self.names = [
            "get_system_status",
            "get_synthetic_self_state",
            "get_functional_self_model",
            "get_user_profile",
            "get_personal_model",
            "recall_user_memory",
            "recall_memory_graph",
            "get_autonomy_status",
            "get_autonomy_pending",
            "search_authorized_learning",
            "get_authorized_learning_status",
            "list_quarantined_learning",
        ]

    def validate_arguments(self, name, args):
        return True, None

    def execute(self, name, args=None):
        args = dict(args or {})
        self.calls.append((name, args))
        if name == "get_system_status":
            data = {
                "ok": True,
                "os": {"system": "Windows", "release": "11", "version": "10.0.26200"},
                "cpu": {"usage_percent": 4.0},
                "memory": {"used_percent": 42.0},
                "gpus": [{"utilization_percent": 3.0}],
            }
        elif name == "get_synthetic_self_state":
            data = {
                "ok": True,
                "affect": {
                    "focus": 0.66,
                    "curiosity": 0.68,
                    "confidence": 0.62,
                    "cognitive_load": 0.20,
                },
                "active_intentions": [],
                "current_focus": "idle",
            }
        elif name == "get_functional_self_model":
            data = {"ok": True, "self_model": {"identity": "JARVIS", "capabilities": ["conversation"], "constraints": ["truth"], "subjective_consciousness_status": "not_established"}}
        elif name == "get_user_profile":
            data = {"ok": True, "profile": {"name": "Tiago", "address_as": "Senhor", "home": {"label": "Furadouro, Ovar"}}}
        elif name == "get_personal_model":
            data = {"ok": True, "model": {"preferences": [], "goals": [], "constraints": [], "projects": [], "jarvis_learning_goals": [{"topic": "programação"}]}}
        elif name == "recall_user_memory":
            data = {"ok": True, "profile": {"name": "Tiago", "address_as": "Senhor", "home": {"label": "Furadouro, Ovar"}}, "facts": [{"fact": "o código de teste desta sessão é AZUL-4729"}]}
        elif name == "recall_memory_graph":
            data = {
                "ok": True,
                "nodes": [
                    {"id": "person:owner", "kind": "person", "label": "OWNER"},
                    {"id": "person:isa", "kind": "person", "label": "ISA"},
                    {"id": "fact:partner", "kind": "fact", "label": "O nome da minha mulher é ISA."},
                ],
                "edges": [{"source": "person:owner", "relation": "PARTNER", "target": "person:isa", "attributes": {"source_fact": "O nome da minha mulher é ISA."}}],
                "decisions": [],
                "projects": [],
            }
        elif name == "get_autonomy_status":
            data = {"ok": True, "mode": "owner_strict", "owner_authority": "absolute", "self_authorization": False, "pending": 0, "active_grants": 0}
        elif name == "get_autonomy_pending":
            data = {"ok": True, "pending": []}
        elif name == "get_authorized_learning_status":
            data = {"ok": True, "entries": 1, "quarantined_entries": 13, "last_repair": {"ok": True, "quarantined": 13}}
        elif name == "list_quarantined_learning":
            data = {"ok": True, "results": [{"quarantine_reason": "legacy_freshness_learning_unverified", "quarantined_at": "2026-09-01T16:00:00+01:00", "original": {"topic": "a versão atual do Python"}}], "count": 1}
        elif name == "search_authorized_learning":
            data = {
                "ok": True,
                "results": [{
                    "topic": "a versão atual do Python",
                    "learned_at": "2026-09-01T16:37:33+01:00",
                    "summary": "evidência insuficiente",
                    "sources": [{"title": "Recent Changes - Python Wiki", "url": "https://wiki.python.org/moin/RecentChanges.html"}],
                    "confidence": 0.94,
                    "source_confidence": 0.94,
                    "confidence_semantics": "source_diversity_score",
                    "claim_confidence": None,
                }],
                "count": 1,
            }
        else:
            data = {"ok": False, "error": "UNKNOWN"}
        return json.dumps(data, ensure_ascii=False)


class AcceptanceHotfixV9Tests(unittest.TestCase):
    def _router(self):
        tools = _Tools()
        return FastCommandRouter(_Events(), tools, _Apps()), tools

    def test_explicit_zero_arg_tool_executes_instead_of_promising(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, executa get_system_status.")
        self.assertTrue(result.handled)
        self.assertEqual(result.tool, "get_system_status")
        self.assertEqual(tools.calls[0][0], "get_system_status")
        self.assertIn("Windows 11", result.response)

    def test_direct_tool_synonyms_execute_real_tool(self):
        for verb in ("corre", "chama", "invoca"):
            router, tools = self._router()
            result = router.dispatch(f"Jarvis, {verb} get_system_status.")
            self.assertTrue(result.handled)
            self.assertEqual(result.tool, "get_system_status")
            self.assertEqual(tools.calls[0][0], "get_system_status")

    def test_use_named_tool_is_not_semantically_substituted_by_fast_router(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, usa recall_user_memory para procurar quem é a minha mulher. Não respondas por inferência.")
        self.assertFalse(result.handled)
        self.assertEqual(tools.calls, [])

    def test_action_truth_blocks_in_progress_and_future_claims(self):
        for draft in (
            "Senhor, estou executando get_system_status. Aguarde um momento.",
            "Vou verificar o status do sistema para si.",
        ):
            guarded, changed = guard_unverified_local_action_claim(
                "Jarvis, executa get_system_status.", draft, successful_tool_calls=0
            )
            self.assertTrue(changed)
            self.assertIn("Não executei", guarded)

    def test_self_state_natural_language_is_classified(self):
        cases = (
            "Desejas algo?",
            "Jarvis, estás curiosa com alguma coisa neste momento?",
            "Há alguma coisa que gostasses de fazer por iniciativa tua agora?",
            "Tens algum pensamento ou objetivo ativo neste momento?",
            "Mostra-me o teu estado interno neste momento.",
            "Qual é o teu nível de confiança neste momento?",
            "Qual é a tua carga cognitiva neste momento?",
            "Como está o teu estado funcional neste momento?",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(classify_request_intent(text).kind, "SELF_STATE_CONVERSATION")

    def test_self_state_metrics_come_from_runtime_tool(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, qual é o teu nível de confiança neste momento?")
        self.assertEqual(result.tool, "get_synthetic_self_state")
        self.assertIn("62.0%", result.response)
        result = router.dispatch("Jarvis, qual é a tua carga cognitiva neste momento?")
        self.assertEqual(result.tool, "get_synthetic_self_state")
        self.assertIn("20.0%", result.response)

    def test_partner_reverse_lookup_uses_relational_memory(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, qual é o nome da minha mulher?")
        self.assertEqual(result.tool, "recall_memory_graph")
        self.assertIn("ISA", result.response)

    def test_owner_profile_read_lists_only_confirmed_local_data(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, o que sabes realmente sobre mim?")
        self.assertEqual(result.tool, "recall_user_memory")
        self.assertIn("nome: Tiago", result.response)
        self.assertIn("AZUL-4729", result.response)
        self.assertNotIn("paix", result.response.lower())

    def test_autonomy_pending_is_actually_read(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, qual é a lista atual de ações autónomas pendentes?")
        self.assertEqual(result.tool, "get_autonomy_pending")
        self.assertIn("Não há ações autónomas pendentes", result.response)

    def test_learning_quarantine_without_authorized_word_still_routes_correctly(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, mostra-me as entradas de aprendizagem que estão em quarentena, sem inventar informações que não estejam registadas.")
        self.assertEqual(result.tool, "list_quarantined_learning")
        self.assertIn("legacy_freshness_learning_unverified", result.response)

    def test_learning_status_is_consistent(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, quantas entradas de aprendizagem autorizada estão ativas e quantas estão em quarentena neste momento?")
        self.assertEqual(result.tool, "get_authorized_learning_status")
        self.assertIn("1 entrada(s) ativa(s)", result.response)
        self.assertIn("13 em quarentena", result.response)
        self.assertNotIn("não há entradas em quarentena", result.response.lower())

    def test_learning_quarantine_uses_quarantine_audit_tool(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, no teu sistema de aprendizagem autorizada, quais são as entradas em quarentena?")
        self.assertEqual(result.tool, "list_quarantined_learning")
        self.assertIn("legacy_freshness_learning_unverified", result.response)

    def test_exact_learning_url_is_not_retyped_by_model(self):
        router, tools = self._router()
        result = router.dispatch('Jarvis, procura na tua aprendizagem autorizada por "Recent Changes - Python Wiki" e devolve exatamente a URL guardada, sem markdown e sem acrescentar texto.')
        self.assertEqual(result.tool, "search_authorized_learning")
        self.assertEqual(result.response, "https://wiki.python.org/moin/RecentChanges.html")

    def test_source_filtered_learning_audit_bypasses_llm_context(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, procura na tua aprendizagem autorizada todos os registos sobre Python cuja fonte seja python.org. Mostra apenas tópico, data e URLs das fontes. Não completes nem interpretes.")
        self.assertTrue(result.handled)
        self.assertEqual(result.tool, "search_authorized_learning")
        self.assertIn("a versão atual do Python", result.response)
        self.assertIn("https://wiki.python.org/moin/RecentChanges.html", result.response)

    def test_quarantine_store_exposes_recorded_reason(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "authorized_learning.jsonl"
            store = AuthorizedLearningStore(path)
            quarantine = path.with_name("authorized_learning_quarantine.jsonl")
            quarantine.write_text(json.dumps({
                "quarantined_at": "2026-09-01T16:00:00+01:00",
                "quarantine_reason": "legacy_freshness_learning_unverified",
                "original": {"topic": "Python", "summary": "old", "sources": []},
            }) + "\n", encoding="utf-8")
            result = store.quarantine_rows("Python", limit=10)
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["results"][0]["quarantine_reason"], "legacy_freshness_learning_unverified")
            self.assertFalse(result["active_rag"])

    def test_version_query_does_not_fall_back_to_unrelated_recent_learning(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "authorized_learning.jsonl"
            store = AuthorizedLearningStore(path)
            store.add(
                topic="a versão atual do Python", query="Python", summary="Sem versão concreta",
                model="qwen3:8b", authorization_token="OWNER", sources=[{"url": "https://python.org"}],
                source_type="authorized_web_research_model_summary",
            )
            result = store.search("3.14", limit=5)
            self.assertEqual(result["count"], 0)

    def test_learning_confidence_question_is_answered_with_core_semantics(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, nesse registo sobre Python, o que significa exatamente a confiança 0.94? É confiança na relevância das fontes ou confiança na informação aprendida?")
        self.assertTrue(result.handled)
        self.assertIn("diversidade/proveniência", result.response)
        self.assertIn("Não é uma probabilidade", result.response)
        self.assertNotIn("confiança na informação aprendida", result.response.lower())

    def test_learning_confidence_semantics_are_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "authorized_learning.jsonl"
            store = AuthorizedLearningStore(path)
            # Use a non relevance-gated source type so this unit test isolates
            # metadata semantics from direct-web topic validation.
            result = store.add(
                topic="Python",
                query="Python",
                summary="Resumo",
                model="qwen3:8b",
                authorization_token="OWNER",
                sources=[{"url": f"https://example{i}.com"} for i in range(4)],
                source_type="authorized_web_research_model_summary",
            )
            self.assertTrue(result["ok"])
            row = store.rows()[0]
            self.assertEqual(row["confidence"], 0.94)
            self.assertEqual(row["source_confidence"], 0.94)
            self.assertEqual(row["confidence_semantics"], "source_diversity_score")
            self.assertIsNone(row["claim_confidence"])

    def test_8k_prompt_is_compact_and_explicit_learning_inspection_skips_rag(self):
        source = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("SYSTEM_PROMPT_8K", source)
        self.assertIn('reason="explicit_inspection_uses_tools"', source)
        self.assertIn("PROMPT_BUDGET_COMPACTED", source)
        self.assertIn("_bounded_request_messages", source)
        start = source.index('SYSTEM_PROMPT_8K = """') + len('SYSTEM_PROMPT_8K = """')
        end = source.index('""".strip()', start)
        self.assertLess(len(source[start:end]), 9000)

    def test_tool_schema_router_prioritizes_explicit_tool_name_and_boundaries(self):
        source = Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        self.assertIn("explicit_tool_names", source)
        self.assertIn('mode="explicit_tool_name"', source)
        self.assertIn("negative_network_constraint", source)
        self.assertIn("marker_present", source)
        self.assertIn("list_quarantined_learning", source)


    def test_self_state_conversation_reads_runtime_state_instead_of_model_improvisation(self):
        cases = (
            ("Jarvis, como te sentes neste momento?", "get_synthetic_self_state", "focada"),
            ("Jarvis, estás curiosa com alguma coisa neste momento?", "get_synthetic_self_state", "curiosidade funcional"),
            ("Jarvis, desejas algo?", "get_synthetic_self_state", "não tenho uma intenção concreta ativa"),
            ("Jarvis, mostra-me o teu estado interno neste momento.", "get_synthetic_self_state", "Estado interno real"),
            ("Jarvis, como está o teu estado funcional neste momento?", "get_functional_self_model", "Modelo funcional local"),
        )
        for text, tool, marker in cases:
            with self.subTest(text=text):
                router, tools = self._router()
                result = router.dispatch(text)
                self.assertTrue(result.handled)
                self.assertEqual(result.tool, tool)
                self.assertEqual(tools.calls[0][0], tool)
                self.assertIn(marker.lower(), result.response.lower())

    def test_full_name_is_not_fabricated_from_first_name(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, qual é o meu nome completo?")
        self.assertTrue(result.handled)
        self.assertEqual(result.tool, "recall_user_memory")
        self.assertIn("não tenho o teu nome completo confirmado", result.response.lower())
        self.assertNotIn("nome completo guardado é Tiago", result.response)

    def test_natural_partner_recall_variants_use_graph(self):
        for text in (
            "Jarvis, quem é a minha mulher?",
            "Jarvis, recorda-te do nome da minha mulher.",
            "Jarvis, recorda-te de quem é a minha mulher?",
        ):
            with self.subTest(text=text):
                router, tools = self._router()
                result = router.dispatch(text)
                self.assertEqual(result.tool, "recall_memory_graph")
                self.assertIn("ISA", result.response)

    def test_personal_model_separates_owner_buckets_from_jarvis_learning_goals(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, mostra-me o modelo pessoal que tens sobre mim.")
        self.assertEqual(result.tool, "get_personal_model")
        self.assertIn("Objetivos de aprendizagem da JARVIS", result.response)
        self.assertIn("programação", result.response)
        self.assertIn("não são interesses do OWNER", result.response)

    def test_explicit_internal_tools_are_executed_not_promised(self):
        for name in ("get_synthetic_self_state", "get_functional_self_model", "get_user_profile", "get_personal_model"):
            with self.subTest(name=name):
                router, tools = self._router()
                result = router.dispatch(f"Jarvis, executa {name}.")
                self.assertTrue(result.handled)
                self.assertEqual(result.tool, name)
                self.assertEqual(tools.calls[0][0], name)
                self.assertNotIn("aguarde", result.response.lower())

    def test_learning_pending_reads_autonomy_queue(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, tens alguma pesquisa ou aprendizagem pendente neste momento?")
        self.assertEqual(result.tool, "get_autonomy_pending")
        self.assertIn("Não há pedidos pendentes", result.response)

    def test_autonomy_state_reads_runtime_status(self):
        router, tools = self._router()
        result = router.dispatch("Jarvis, qual é o teu estado de autonomia neste momento?")
        self.assertEqual(result.tool, "get_autonomy_status")
        self.assertIn("owner_strict", result.response)
        self.assertIn("autoautorização=False", result.response)

    def test_learning_search_reports_semantic_match_without_claiming_literal_version(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "authorized_learning.jsonl"
            store = AuthorizedLearningStore(path)
            store.add(
                topic="a versão atual do Python", query="Python", summary="evidência insuficiente",
                model="qwen3:8b", authorization_token="OWNER", sources=[{"url": "https://wiki.python.org/moin/PythonBooks"}],
                source_type="authorized_web_research_model_summary",
            )
            result = store.search("3.14", limit=5)
            self.assertEqual(result["count"], 0)



if __name__ == "__main__":
    unittest.main()
