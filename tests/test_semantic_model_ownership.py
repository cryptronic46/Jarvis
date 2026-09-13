import unittest
from types import SimpleNamespace

from jarvis_core.cli import (
    route_runtime_request,
)
from jarvis_core.services.memory_retrieval import (
    MemoryRetrievalCoordinator,
)
from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


class FakeEvents:
    def __init__(self):
        self.rows = []

    def emit(
        self,
        name,
        **data,
    ):
        self.rows.append(
            (name, data)
        )


class FakeFastRouter:
    def __init__(self):
        self.calls = []

    def dispatch(
        self,
        text,
        *,
        request=None,
    ):
        self.calls.append(
            {
                "text": text,
                "request": request,
            }
        )

        return SimpleNamespace(
            handled=True,
            response="FAST_RESPONSE",
            route="test_fast",
            tool="none",
        )


class FakeHybrid:
    def __init__(self):
        self.calls = []

    def ask(
        self,
        text,
        *,
        request=None,
    ):
        self.calls.append(
            {
                "text": text,
                "request": request,
            }
        )

        return SimpleNamespace(
            text="MODEL_RESPONSE",
            route="LOCAL/model_owned",
        )


def semantic_context():
    return (
        [],
        {
            "brave": "brave",
        },
        None,
    )


class SemanticModelOwnershipTests(
    unittest.TestCase
):
    def _run(
        self,
        text,
    ):
        events = FakeEvents()
        fast = FakeFastRouter()
        hybrid = FakeHybrid()

        result = route_runtime_request(
            text,
            source="terminal",
            semantic_context_inputs=(
                semantic_context
            ),
            events=events,
            fast_router=fast,
            hybrid_brain=hybrid,
        )

        return (
            result,
            events,
            fast,
            hybrid,
        )

    def test_owner_questions_become_grounded_model_conversation(
        self,
    ):
        request = resolve_semantic_request(
            "Ainda sabes o meu nome?"
        )

        self.assertEqual(
            request.intent,
            "GENERAL_CONVERSATION",
        )

        self.assertEqual(
            request.domain,
            "owner_memory",
        )

        self.assertEqual(
            request.subject,
            "OWNER",
        )

        allowed, reason = (
            MemoryRetrievalCoordinator.eligible(
                request
            )
        )

        self.assertTrue(
            allowed,
            reason,
        )

    def test_jarvis_subject_questions_become_identity_dialogue(
        self,
    ):
        request = resolve_semantic_request(
            "Qual e a tua profissao?"
        )

        self.assertEqual(
            request.intent,
            "IDENTITY_DIALOGUE",
        )

        self.assertEqual(
            request.domain,
            "jarvis_self",
        )

        self.assertEqual(
            request.subject,
            "JARVIS",
        )

    def test_model_owned_intents_never_call_fast_router(
        self,
    ):
        cases = (
            "Provoca-me",
            "Como te sentes hoje?",
            "O que podes fazer?",
            "Ainda sabes o meu nome?",
            "Qual e a tua profissao?",
        )

        for text in cases:
            with self.subTest(
                text=text
            ):
                (
                    result,
                    events,
                    fast,
                    hybrid,
                ) = self._run(text)

                self.assertEqual(
                    fast.calls,
                    [],
                )

                self.assertEqual(
                    len(hybrid.calls),
                    1,
                )

                self.assertEqual(
                    result[0],
                    "MODEL_RESPONSE",
                )

                self.assertTrue(
                    any(
                        name
                        == "FAST_ROUTER_BYPASSED"
                        for name, _
                        in events.rows
                    )
                )

    def test_retired_self_state_fast_routes_are_model_owned(
        self,
    ):
        cases = (
            "nivel de confian\u00e7a neste momento",
            "qual \u00e9 a tua carga cognitiva",
            "como est\u00e1 o teu estado funcional",
            "est\u00e1s curiosa",
        )

        for text in cases:
            with self.subTest(
                text=text
            ):
                request = resolve_semantic_request(
                    text
                )

                self.assertEqual(
                    request.intent,
                    "SELF_STATE",
                )

                self.assertEqual(
                    request.preferred_tool,
                    "get_synthetic_self_state",
                )

                (
                    result,
                    events,
                    fast,
                    hybrid,
                ) = self._run(text)

                self.assertEqual(
                    fast.calls,
                    [],
                )

                self.assertEqual(
                    len(hybrid.calls),
                    1,
                )

                self.assertEqual(
                    result[0],
                    "MODEL_RESPONSE",
                )

                self.assertTrue(
                    any(
                        name
                        == "FAST_ROUTER_BYPASSED"
                        for name, _
                        in events.rows
                    )
                )

    def test_owner_context_gaps_are_model_owned(
        self,
    ):
        cases = (
            "Como me chamo?",
            "Quem sou eu?",
            "Mostra o meu perfil",
            "Fala-me sobre mim",
            "O que pensas de mim?",
            "O que achas de mim?",
            "Como me v\u00eas?",
            "Qual \u00e9 a tua opini\u00e3o sobre mim?",
            "Que objetivos tenho?",
            "O que quero alcan\u00e7ar?",
            "O que quero aprender?",
            "O que ando a estudar?",
            "Que temas quero aprender?",
            "Onde moro?",
            "Em que cidade vivo?",
            "Mostra o teu modelo sobre mim",
            "Como me modelas?",
        )

        for text in cases:
            with self.subTest(
                text=text
            ):
                request = resolve_semantic_request(
                    text
                )

                self.assertEqual(
                    request.intent,
                    "GENERAL_CONVERSATION",
                )

                self.assertEqual(
                    request.domain,
                    "owner_memory",
                )

                self.assertEqual(
                    request.subject,
                    "OWNER",
                )

                self.assertEqual(
                    request.action,
                    "discuss_owner_context",
                )

                self.assertFalse(
                    request.requires_tool
                )

                self.assertIsNone(
                    request.preferred_tool
                )

                (
                    result,
                    events,
                    fast,
                    hybrid,
                ) = self._run(
                    text
                )

                self.assertEqual(
                    fast.calls,
                    [],
                )

                self.assertEqual(
                    len(hybrid.calls),
                    1,
                )

                self.assertEqual(
                    result[0],
                    "MODEL_RESPONSE",
                )

    def test_legacy_owner_fast_triggers_are_model_owned(
        self,
    ):
        cases = (
            "de que forma tu me ves",
            "de que forma me ves",
            "como tu me ves",
            "como me ves",
            "quais sao os meus objetivos",
            "quais os meus objetivos",
            "meus objetivos atuais",
            "recorda te de onde eu moro",
            "recordas te de onde eu moro",
            "onde eu moro",
        )

        for phrase in cases:
            for text in (
                phrase,
                "Jarvis, " + phrase,
            ):
                with self.subTest(
                    text=text
                ):
                    request = resolve_semantic_request(
                        text
                    )

                    self.assertEqual(
                        request.intent,
                        "GENERAL_CONVERSATION",
                    )

                    self.assertEqual(
                        request.domain,
                        "owner_memory",
                    )

                    self.assertEqual(
                        request.subject,
                        "OWNER",
                    )

                    self.assertEqual(
                        request.action,
                        "discuss_owner_context",
                    )

                    self.assertFalse(
                        request.requires_tool
                    )

                    self.assertIsNone(
                        request.preferred_tool
                    )

                    (
                        result,
                        events,
                        fast,
                        hybrid,
                    ) = self._run(
                        text
                    )

                    self.assertEqual(
                        fast.calls,
                        [],
                    )

                    self.assertEqual(
                        len(hybrid.calls),
                        1,
                    )

                    self.assertEqual(
                        result[0],
                        "MODEL_RESPONSE",
                    )

    def test_remaining_legacy_memory_concepts_are_model_owned(
        self,
    ):
        cases = (
            "mostra me o meu perfil de utilizador",
            "mostra o meu perfil de utilizador",
            "qual e o meu nome completo",
            "Qual \u00e9 o meu nome completo?",
            "meu nome completo",
            "o que te lembras de mim",
            "mostra a minha memoria",
            "mostra a memoria",
            "quais sao os meus objetivos de aprendizagem",
            "meus objetivos de aprendizagem",
            "mostra-me o modelo pessoal que tens sobre mim",
            "modelo pessoal que tens sobre mim",
            "meu modelo pessoal",
            "modelo pessoal sobre mim",
            "recorda-te do nome da minha mulher",
            "recordas-te do nome da minha mulher",
            "recorda-te de quem e a minha mulher",
            "recordas-te de quem e a minha mulher",
            "quem e a Ana para mim",
            (
                "Recorda o que te pedi para guardar "
                "na memoria local ha pouco"
            ),
            (
                "Lembra-te do que te pedi para memorizar "
                "ha pouco"
            ),
            "qual era o codigo de teste",
            "qual foi o codigo de teste",
            "codigo de teste desta sessao",
        )

        model_intents = {
            "GENERAL_CONVERSATION",
            "SOCIAL_INTERACTION",
            "KNOWLEDGE_CAPABILITY",
        }

        for phrase in cases:
            for text in (
                phrase,
                "Jarvis, " + phrase,
            ):
                with self.subTest(
                    text=text
                ):
                    request = resolve_semantic_request(
                        text
                    )

                    self.assertIn(
                        request.intent,
                        model_intents,
                    )

                    self.assertFalse(
                        request.requires_tool
                    )

                    self.assertIsNone(
                        request.preferred_tool
                    )

                    (
                        result,
                        events,
                        fast,
                        hybrid,
                    ) = self._run(
                        text
                    )

                    self.assertEqual(
                        fast.calls,
                        [],
                    )

                    self.assertEqual(
                        len(hybrid.calls),
                        1,
                    )

                    self.assertEqual(
                        result[0],
                        "MODEL_RESPONSE",
                    )


    def test_recent_explicit_memory_has_semantic_retrieval_action(
        self,
    ):
        cases = (
            (
                "Recorda o que te pedi para guardar "
                "na memoria local ha pouco"
            ),
            (
                "Lembra-te do que te pedi para memorizar "
                "ha pouco"
            ),
        )

        for phrase in cases:
            for text in (
                phrase,
                "Jarvis, " + phrase,
            ):
                with self.subTest(
                    text=text
                ):
                    request = (
                        resolve_semantic_request(
                            text
                        )
                    )

                    self.assertEqual(
                        request.intent,
                        "GENERAL_CONVERSATION",
                    )

                    self.assertEqual(
                        request.domain,
                        "owner_memory",
                    )

                    self.assertEqual(
                        request.subject,
                        "OWNER",
                    )

                    self.assertEqual(
                        request.action,
                        (
                            "recall_recent_"
                            "explicit_memory"
                        ),
                    )

                    self.assertFalse(
                        request.requires_tool
                    )

                    self.assertIsNone(
                        request.preferred_tool
                    )

                    (
                        result,
                        events,
                        fast,
                        hybrid,
                    ) = self._run(
                        text
                    )

                    self.assertEqual(
                        fast.calls,
                        [],
                    )

                    self.assertEqual(
                        len(hybrid.calls),
                        1,
                    )

                    self.assertEqual(
                        result[0],
                        "MODEL_RESPONSE",
                    )

    def test_remaining_self_state_gaps_are_model_owned(
        self,
    ):
        cases = (
            "o que sentes",
            "o que sentes agora",
            "o que sentes neste momento",
            "mostra o teu estado interno",
            "objetivo ativo",
            "Jarvis, o que sentes agora",
            "Jarvis, mostra o teu estado interno",
            "Jarvis, objetivo ativo",
        )

        for text in cases:
            with self.subTest(
                text=text
            ):
                request = resolve_semantic_request(
                    text
                )

                self.assertEqual(
                    request.intent,
                    "SELF_STATE",
                )

                self.assertEqual(
                    request.domain,
                    "jarvis_self",
                )

                self.assertEqual(
                    request.subject,
                    "JARVIS",
                )

                self.assertEqual(
                    request.preferred_tool,
                    "get_synthetic_self_state",
                )

                self.assertGreaterEqual(
                    float(
                        request.confidence
                    ),
                    0.95,
                )

                (
                    result,
                    events,
                    fast,
                    hybrid,
                ) = self._run(
                    text
                )

                self.assertEqual(
                    fast.calls,
                    [],
                )

                self.assertEqual(
                    len(hybrid.calls),
                    1,
                )

                self.assertEqual(
                    result[0],
                    "MODEL_RESPONSE",
                )

    def test_deterministic_operational_action_still_uses_fast_router(
        self,
    ):
        (
            result,
            events,
            fast,
            hybrid,
        ) = self._run(
            "Abre o Brave"
        )

        self.assertEqual(
            len(fast.calls),
            1,
        )

        self.assertEqual(
            hybrid.calls,
            [],
        )

        self.assertEqual(
            result[0],
            "FAST_RESPONSE",
        )

        self.assertTrue(
            result[1].startswith(
                "FAST/"
            )
        )

    def test_migrated_volume_operation_is_semantically_owned(
        self,
    ):
        request = resolve_semantic_request(
            "Coloca o volume a 30%"
        )

        self.assertEqual(
            request.intent,
            "OPERATIONAL_ACTION",
        )

        self.assertEqual(
            request.action,
            "set_volume",
        )

        self.assertEqual(
            request.preferred_tool,
            "set_master_volume",
        )

        self.assertEqual(
            request.as_dict()[
                "tool_arguments"
            ],
            {
                "percent": 30,
            },
        )

        (
            result,
            events,
            fast,
            hybrid,
        ) = self._run(
            "Coloca o volume a 30%"
        )

        self.assertEqual(
            len(fast.calls),
            1,
        )

        self.assertEqual(
            hybrid.calls,
            [],
        )

        self.assertEqual(
            result[0],
            "FAST_RESPONSE",
        )


if __name__ == "__main__":
    unittest.main()
