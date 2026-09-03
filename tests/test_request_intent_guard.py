import unittest
from pathlib import Path

from jarvis_core.services.request_intent import (
    capability_answer_needs_repair,
    classify_request_intent,
    intent_contract,
    repair_capability_answer,
    sanitize_assistant_text,
)


class RequestIntentGuardTests(unittest.TestCase):
    def test_sabes_usar_is_knowledge_not_execution(self):
        result = classify_request_intent("Jarvis, sabes usar todas as ferramentas do Kali Linux?")
        self.assertEqual(result.kind, "KNOWLEDGE_CAPABILITY")

    def test_explicit_test_is_operational(self):
        result = classify_request_intent("Jarvis, testa a VM 192.168.56.10")
        self.assertEqual(result.kind, "OPERATIONAL_ACTION")

    def test_knowledge_contract_forbids_permission_lecture(self):
        contract = intent_contract("Sabes usar o Nmap?")
        self.assertIn("intent=KNOWLEDGE_CAPABILITY", contract)
        self.assertIn("Do not turn a knowledge question into a refusal", contract)

    def test_detects_capability_mismatch(self):
        self.assertTrue(
            capability_answer_needs_repair(
                "Sabes usar todas as ferramentas do Kali Linux?",
                "Senhor, não posso usar todas porque exigem autorização.",
            )
        )

    def test_normal_direct_answer_does_not_need_repair(self):
        self.assertFalse(
            capability_answer_needs_repair(
                "Sabes usar todas as ferramentas do Kali Linux?",
                "Senhor, conheço o funcionamento e uso de muitas delas, embora não seja rigoroso afirmar domínio absoluto de todas sem as verificar.",
            )
        )

    def test_emoji_is_removed_unless_requested(self):
        self.assertEqual(sanitize_assistant_text("Claro, Senhor. 😊"), "Claro, Senhor.")
        self.assertIn("😊", sanitize_assistant_text("Claro 😊", user_text="responde com emoji"))


    def test_capability_repair_is_tool_free(self):
        class Events:
            def __init__(self):
                self.names = []
            def emit(self, name, **kwargs):
                self.names.append(name)

        class Response:
            message = type("Message", (), {
                "content": (
                    "Senhor, conheço o funcionamento e a utilização de muitas ferramentas do Kali Linux; "
                    "não seria rigoroso afirmar domínio absoluto de todas sem as verificar individualmente."
                )
            })()

        class Client:
            def __init__(self):
                self.calls = []
            def chat(self, **kwargs):
                self.calls.append(kwargs)
                return Response()

        client = Client()
        events = Events()
        settings = type("Settings", (), {"model": "qwen", "llm_temperature": 0.2})()
        plan = type("Plan", (), {"keep_alive": "5m", "num_ctx": 4096, "num_predict": 220})()
        repaired, model_used = repair_capability_answer(
            client=client,
            settings=settings,
            events=events,
            user_text="Jarvis, sabes usar todas as ferramentas do Kali Linux?",
            draft="Senhor, não posso usar todas porque exigem autorização e são eticamente restritas.",
            plan=plan,
        )
        self.assertTrue(model_used)
        self.assertIn("conheço o funcionamento", repaired)
        self.assertNotIn("não posso", repaired.lower())
        self.assertEqual(len(client.calls), 1)
        self.assertNotIn("tools", client.calls[0])
        self.assertIn("CAPABILITY_ANSWER_REPAIR_FINISHED", events.names)

    def test_operational_request_never_enters_capability_repair(self):
        class Client:
            def __init__(self):
                self.calls = []
            def chat(self, **kwargs):
                self.calls.append(kwargs)
                raise AssertionError("repair should not run")

        class Events:
            def emit(self, name, **kwargs):
                pass

        client = Client()
        settings = type("Settings", (), {"model": "qwen", "llm_temperature": 0.2})()
        plan = type("Plan", (), {"keep_alive": "5m", "num_ctx": 4096, "num_predict": 220})()
        draft = "O alvo não está autorizado como LAB."
        repaired, model_used = repair_capability_answer(
            client=client,
            settings=settings,
            events=Events(),
            user_text="Jarvis, testa a VM 192.168.56.10",
            draft=draft,
            plan=plan,
        )
        self.assertFalse(model_used)
        self.assertEqual(repaired, draft)
        self.assertEqual(client.calls, [])

    def test_brain_contains_capability_repair_path(self):
        brain = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        service = Path("jarvis_core/services/request_intent.py").read_text(encoding="utf-8")
        self.assertIn("_repair_capability_answer", brain)
        self.assertIn("repair_capability_answer", brain)
        self.assertIn("CAPABILITY_ANSWER_REPAIR_STARTED", service)
        self.assertIn("Knowledge is not execution", brain)


if __name__ == "__main__":
    unittest.main()
