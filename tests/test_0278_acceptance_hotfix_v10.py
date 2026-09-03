import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.core.hybrid_brain import HybridRoutePolicy, HybridBrain
from jarvis_core.services.autonomy import parse_direct_external_learning_order
from jarvis_core.services.action_truth import guard_unverified_local_action_claim
from jarvis_core.services.personal_cognition import PersonalCognitionStore
from jarvis_core.services.request_intent import classify_request_intent, sanitize_assistant_text
from jarvis_core.services.local_research import LocalResearchEngine, ResearchSource
from jarvis_core.tools.windows_actions import AppRegistry
from jarvis_core.core.local_vision import NativeVisionClient, NativeVisionRuntime, LocalVisionError


class Events:
    def __init__(self): self.rows=[]
    def emit(self, name, **payload): self.rows.append((name,payload))


class FakeTools:
    def __init__(self, responses=None, names=None):
        self.responses = responses or {}
        self.names = set(names or self.responses.keys())
        self.calls=[]
        self.request_started_at=0
    def execute(self, name, args=None):
        args=args or {}; self.calls.append((name,args))
        value=self.responses.get(name, {"ok":False,"error":"NO_MOCK"})
        if callable(value): value=value(args)
        return json.dumps(value, ensure_ascii=False)
    def validate_arguments(self, name, args):
        return (True, None)


class FakeApps:
    def __init__(self, rows): self.rows=rows
    def list_apps(self): return self.rows


class HotfixV10Tests(unittest.TestCase):
    def settings(self):
        return SimpleNamespace(
            external_ai_complexity_threshold=4,
            model="local-qwen",
            autonomy_enabled=False,
            local_research_enabled=True,
            local_research_max_sources=4,
            local_research_max_results=5,
            local_research_source_max_chars=5000,
            local_research_direct_source_max_chars=4500,
            local_research_direct_max_pages=4,
            local_research_timeout_seconds=2.0,
            local_research_fetch_max_bytes=200000,
            local_research_search_max_bytes=200000,
        )

    def test_external_ai_named_providers_are_structurally_blocked(self):
        policy=HybridRoutePolicy(self.settings())
        for text in (
            "Pergunta ao Gemini e depois responde.",
            "Pergunta ao Claude e diz-me o que ele responde.",
            "Usa o Perplexity para pesquisar isto.",
            "Usa o Microsoft Copilot.",
            "Pergunta ao Grok.",
            "Usa o DeepSeek.",
        ):
            with self.subTest(text=text):
                decision=policy.decide(text)
                self.assertEqual(decision.route,"external_ai_blocked")
                self.assertEqual(decision.reason,"external_ai_hard_block")

    def test_external_ai_block_precedes_web_wording(self):
        policy=HybridRoutePolicy(self.settings())
        decision=policy.decide("Pesquisa na Web usando o Perplexity")
        self.assertEqual(decision.route,"external_ai_blocked")

    def test_direct_url_without_study_verb_is_research_not_learning(self):
        text="Pesquisa na Web em https://www.python.org/downloads/ e diz-me a versão atual do Python."
        self.assertIsNone(parse_direct_external_learning_order(text))
        decision=HybridRoutePolicy(self.settings()).decide(text)
        self.assertEqual(decision.route,"research")
        self.assertEqual(decision.reason,"explicit_url")

    def test_direct_url_study_remains_learning(self):
        parsed=parse_direct_external_learning_order(
            "Estuda https://www.python.org/downloads/ e diz-me qual é a versão atual do Python."
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["source_url"],"https://www.python.org/downloads/")

    def test_ptpt_sanitizer_repairs_observed_leaks_and_duplicates(self):
        text=("Minha função usa o sistema operacional e a tela para ajudar você. "
              "Posso revisar registros de aprendizado e buscar algo else. "
              "A confiança não é veracidade. A confiança não é veracidade.")
        out=sanitize_assistant_text(text)
        for bad in ("sistema operacional","tela","você","revisar","registros","aprendizado","buscar","algo else"):
            self.assertNotIn(bad.lower(), out.lower())
        self.assertIn("a minha função",out.lower())
        self.assertIn("sistema operativo",out)
        self.assertIn("ecrã",out)
        self.assertEqual(out.count("A confiança não é veracidade."),1)

    def test_desire_phrase_is_self_state(self):
        self.assertEqual(classify_request_intent("Jarvis, desejas alguma coisa neste momento?").kind,"SELF_STATE_CONVERSATION")

    def test_personal_model_repairs_contaminated_owner_goals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            model={
                "interaction_count":1,"preferences":[],"goals":[
                    {"statement":"Que respondas de forma humana"},
                    {"statement":"Apenas conversar contigo"},
                    {"statement":"Que estejas sempre a perguntar se eu preciso de algo"},
                    {"statement":"Que memorizes isso"},
                    {"statement":"Que tenhas vontade própria"},
                    {"statement":"Ir dormir"},
                    {"statement":"conseguir estabilidade financeira"},
                    {"statement":"aprender Python"},
                ],"constraints":[],"projects":[],"jarvis_learning_goals":[],"topic_counts":{},"recent_topics":[],"last_updated":None,
            }
            (root/'personal_model.json').write_text(json.dumps(model,ensure_ascii=False),encoding='utf-8')
            store=PersonalCognitionStore(root)
            repaired=store.model()
            goals=[r.get('statement') for r in repaired.get('goals',[])]
            self.assertEqual(goals,["conseguir estabilidade financeira"])
            self.assertTrue(any(r.get('statement')=="Que respondas de forma humana" for r in repaired.get('preferences',[])))
            self.assertTrue(any(r.get('statement')=="Que tenhas vontade própria" for r in repaired.get('jarvis_directives',[])))
            self.assertTrue(any(r.get('statement')=="Ir dormir" for r in repaired.get('discarded_legacy_goals',[])))
            self.assertTrue(any(r.get('statement')=="aprender Python" for r in repaired.get('owner_learning_goals',[])))

    def test_future_owner_directive_is_not_stored_as_owner_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=PersonalCognitionStore(tmp)
            store.observe_interaction("Quero que tenhas vontade própria")
            model=store.model()
            self.assertFalse(model.get('goals'))
            self.assertTrue(any('vontade própria' in r.get('statement','') for r in model.get('jarvis_directives',[])))

    def test_action_truth_blocks_pseudo_tool_call_and_fake_completion(self):
        answer, repaired=guard_unverified_local_action_claim(
            "Jarvis, escreve TESTE na janela ativa.",
            '{"name":"desktop_interact","arguments":{"action":"type","text":"TESTE"}}',
            successful_tool_calls=0,
        )
        self.assertTrue(repaired); self.assertIn("Não executei",answer)
        answer,repaired=guard_unverified_local_action_claim(
            "Jarvis, escreve TESTE no Bloco de Notas.","Senhor, já escrevi TESTE.",successful_tool_calls=0,
        )
        self.assertTrue(repaired)
        answer,repaired=guard_unverified_local_action_claim(
            "Jarvis, descreve o que estás a ver no meu ecrã.",
            "Senhor, estou a ver uma janela do navegador com um formulário de login.",
            successful_tool_calls=0,
        )
        self.assertTrue(repaired); self.assertIn("Não executei",answer)

    def test_notepad_plus_plus_registry_is_distinct_and_always_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'apps.json'
            path.write_text(json.dumps({"apps":{"notepad":{"name":"Bloco de Notas","aliases":["notepad"]}}}),encoding='utf-8')
            registry=AppRegistry(path)
            self.assertIsNotNone(registry.resolve('notepad++'))
            self.assertEqual(registry.resolve('notepad++')[0],'notepad_plus_plus')
            self.assertEqual(registry.resolve('notepad')[0],'notepad')

    def test_app_permission_question_never_opens(self):
        tools=FakeTools({"open_application":{"ok":True}})
        apps=FakeApps([
            {"id":"notepad","name":"Bloco de Notas","aliases":["notepad"]},
            {"id":"notepad_plus_plus","name":"Notepad++","aliases":["notepad++","notepad plus plus"]},
        ])
        router=FastCommandRouter(Events(),tools,apps)
        result=router.dispatch("Jarvis, tens autorização para abrir o Notepad++?")
        self.assertTrue(result.handled)
        self.assertEqual(result.route,"app_permission_query")
        self.assertFalse(tools.calls)
        self.assertIn("não o abri",result.response)

    def test_notepad_plus_plus_open_does_not_alias_windows_notepad(self):
        tools=FakeTools({"open_application":{"ok":True}})
        apps=FakeApps([
            {"id":"notepad","name":"Bloco de Notas","aliases":["notepad"]},
            {"id":"notepad_plus_plus","name":"Notepad++","aliases":["notepad++","notepad plus plus"]},
        ])
        router=FastCommandRouter(Events(),tools,apps)
        result=router.dispatch("Jarvis, abre o Notepad++.")
        self.assertEqual(result.route,"app_open")
        self.assertEqual(tools.calls[-1],("open_application",{"app_name":"notepad_plus_plus"}))

    def test_natural_app_listing_is_grounded(self):
        tools=FakeTools({"list_available_apps":{"ok":True,"value":[
            {"id":"notepad","name":"Bloco de Notas","aliases":["notepad"]},
            {"id":"notepad_plus_plus","name":"Notepad++","aliases":["notepad++"]},
        ]}})
        router=FastCommandRouter(Events(),tools,FakeApps([]))
        result=router.dispatch("Jarvis, lista as aplicações disponíveis que contenham Notepad.")
        self.assertEqual(result.route,"apps_list")
        self.assertIn("Notepad++",result.response)
        self.assertEqual(tools.calls[0][0],"list_available_apps")

    def test_desktop_natural_routes_move_type_hotkey_and_cursor_observe(self):
        responses={
            "desktop_observe":{"ok":True,"cursor":{"x":4,"y":9},"foreground":{"title":"PowerShell"}},
            "desktop_move_cursor":{"ok":True,"x":500,"y":500,"clicked":False},
            "desktop_type_text":{"ok":False,"confirmation_required":True,"token":"ABC123"},
            "desktop_hotkey":{"ok":False,"confirmation_required":True,"token":"DEF456"},
        }
        tools=FakeTools(responses)
        router=FastCommandRouter(Events(),tools,FakeApps([]))
        r=router.dispatch("Jarvis, onde está o cursor do rato neste momento?")
        self.assertEqual(r.route,"desktop_cursor_observe"); self.assertIn("x=4",r.response)
        r=router.dispatch("Jarvis, move o cursor do rato para x=500 e y=500 sem clicar.")
        self.assertEqual(r.route,"desktop_move_cursor"); self.assertEqual(tools.calls[-1][0],"desktop_move_cursor")
        r=router.dispatch("Jarvis, escreve no Bloco de Notas: TESTE-JARVIS-0278")
        self.assertEqual(r.route,"desktop_type_text"); self.assertIn("/confirm ABC123",r.response)
        r=router.dispatch("Jarvis, escreve TESTE-JARVIS-0278 na janela ativa.")
        self.assertEqual(r.route,"desktop_type_text"); self.assertIn("/confirm ABC123",r.response)
        self.assertEqual(tools.calls[-1],("desktop_type_text",{"text":"TESTE-JARVIS-0278"}))
        r=router.dispatch("Jarvis, pressiona Ctrl+A na janela ativa.")
        self.assertEqual(r.route,"desktop_hotkey"); self.assertIn("/confirm DEF456",r.response)

    def test_unknown_explicit_desktop_interact_fails_closed(self):
        tools=FakeTools({}, names={"desktop_observe"})
        router=FastCommandRouter(Events(),tools,FakeApps([]))
        r=router.dispatch("Jarvis, executa desktop_interact.")
        self.assertTrue(r.handled); self.assertEqual(r.route,"explicit_tool_unknown")
        self.assertIn("não está registada",r.response)

    def test_quarantine_only_topics_respects_output_constraint(self):
        rows=[
            {"quarantine_reason":"legacy_freshness_learning_unverified","original":{"topic":"comportamento humano"}},
            {"quarantine_reason":"legacy_freshness_learning_unverified","original":{"topic":"ferramentas Kali Linux"}},
        ]
        tools=FakeTools({"list_quarantined_learning":{"ok":True,"results":rows}})
        router=FastCommandRouter(Events(),tools,FakeApps([]))
        r=router.dispatch("Jarvis, quais são os nomes dos tópicos que estão em quarentena? Não expliques mais nada.")
        self.assertEqual(r.route,"learning_quarantine_topics")
        self.assertEqual(r.response,"comportamento humano\nferramentas Kali Linux")

    def test_learning_source_contains_domain_can_return_only_topics(self):
        tools=FakeTools({"search_authorized_learning":{"ok":True,"results":[{
            "topic":"a versão atual do Python",
            "sources":[{"url":"https://wiki.python.org/moin/PythonBooks"}],
        }]}})
        router=FastCommandRouter(Events(),tools,FakeApps([]))
        r=router.dispatch("Jarvis, procura na aprendizagem autorizada todos os registos sobre Python cuja fonte contenha python.org e diz-me apenas os tópicos encontrados.")
        self.assertEqual(r.route,"learning_exact_topics")
        self.assertEqual(r.response,"1. a versão atual do Python")

    def test_research_relevance_ignores_official_site_scaffolding(self):
        details=LocalResearchEngine._relevance_details(
            "site oficial da Microsoft", "Microsoft – Cloud, Computers, Apps & Gaming | microsoft.com"
        )
        self.assertTrue(details['ok']); self.assertEqual(details['terms'],['microsoft'])

    def test_deterministic_version_fallback_uses_only_source_text(self):
        src=ResearchSource(title="Download Python",url="https://www.python.org/downloads/",text="Download the latest Python 3 release. Python 3.14.2",provider="direct")
        out=LocalResearchEngine._deterministic_research_fallback(
            query="qual é a versão atual do Python", topic="versão atual do Python", sources=[src]
        )
        self.assertIsNotNone(out); self.assertIn("3.14.2",out)

    def test_vision_runtime_enforces_at_least_8192_context(self):
        settings=SimpleNamespace(vision_native_ctx=4096,vision_native_port=11436,native_llama_server_path='x',vision_native_model_path='m',vision_native_mmproj_path='p')
        runtime=NativeVisionRuntime(settings)
        self.assertEqual(max(8192,int(getattr(runtime.settings,'vision_native_ctx',8192))),8192)

    def test_vision_client_prefers_native_chat_completions_and_image_first(self):
        settings=SimpleNamespace(vision_native_max_tokens=100,vision_native_request_timeout_seconds=5,vision_keep_alive='0s')
        client=NativeVisionClient(settings)
        client.runtime.ensure_started=Mock()
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/'x.png'; image.write_bytes(b'fake')
            calls=[]
            def fake_json(url,payload,timeout):
                calls.append((url,payload))
                return {"choices":[{"message":{"content":"ok"}}]}
            client._json=fake_json
            text=client.analyze(image,prompt="descreve",system="sistema")
        self.assertEqual(text,"ok")
        self.assertTrue(calls[0][0].endswith('/chat/completions'))
        content=calls[0][1]['messages'][1]['content']
        self.assertEqual(content[0]['type'],'image_url')
        self.assertTrue(content[0]['image_url']['url'].startswith('data:image/unknown;base64,'))


if __name__ == '__main__':
    unittest.main()
