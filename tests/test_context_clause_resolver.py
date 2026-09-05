import unittest
from pathlib import Path

from jarvis_core.services.context_clause_resolver import (
    resolve_context_clauses,
)
from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


APP_ALIASES = {
    "brave": "brave",
    "brave browser": "brave",
    "spotify": "spotify",
}


class ContextClauseResolverTests(
    unittest.TestCase
):
    def test_direct_self_state_without_context(self):
        cases = (
            "Qual e a tua confianca?",
            "Qual o teu nivel de confianca?",
            "Estas focada?",
            "Tens alguma intencao ativa?",
            "O que te esta a motivar?",
            "Resume o teu estado atual numa frase.",
        )

        for text in cases:
            with self.subTest(text=text):
                result = (
                    resolve_context_clauses(
                        text
                    )
                )

                self.assertEqual(
                    result.kind,
                    "SELF_STATE",
                )

                self.assertEqual(
                    result.referent,
                    "jarvis_self_state",
                )

                self.assertGreaterEqual(
                    result.confidence,
                    0.95,
                )

    def test_elliptical_self_state_with_context(self):
        recent = [
            {
                "user": "Como te sentes?",
                "assistant": (
                    "Estou focada e curiosa."
                ),
                "route": (
                    "FAST/self_state_affect"
                ),
            }
        ]

        cases = (
            "E de curiosidade?",
            "Em que?",
            "E alguma preocupacao?",
            "Isso mudou desde ha pouco?",
        )

        for text in cases:
            with self.subTest(text=text):
                result = (
                    resolve_context_clauses(
                        text,
                        recent_turns=recent,
                    )
                )

                self.assertEqual(
                    result.kind,
                    "SELF_STATE",
                )

    def test_elliptical_self_state_fails_closed_without_context(
        self,
    ):
        cases = (
            "E de curiosidade?",
            "Em que?",
            "E alguma preocupacao?",
            "Isso mudou desde ha pouco?",
        )

        for text in cases:
            with self.subTest(text=text):
                result = (
                    resolve_context_clauses(
                        text
                    )
                )

                self.assertEqual(
                    result.kind,
                    "NONE",
                )

    def test_compound_app_polarity(
        self,
    ):
        cases = (
            (
                "Nao abras o Spotify, abre o Brave.",
                "brave",
            ),
            (
                "Nao abras o Brave, abre o Spotify.",
                "spotify",
            ),
            (
                "Abre o Brave, nao abras o Spotify.",
                "brave",
            ),
            (
                "Abre o Spotify, mas nao o Brave.",
                "spotify",
            ),
            (
                "Nao quero Spotify; quero Brave.",
                "brave",
            ),
            (
                "Quero Brave, nao Spotify.",
                "brave",
            ),
            (
                "Em vez do Spotify, abre o Brave.",
                "brave",
            ),
            (
                "Abre o Brave em vez do Spotify.",
                "brave",
            ),
            (
                "Spotify nao. Brave sim.",
                "brave",
            ),
        )

        for text, target in cases:
            with self.subTest(text=text):
                result = (
                    resolve_context_clauses(
                        text,
                        app_aliases=APP_ALIASES,
                    )
                )

                self.assertEqual(
                    result.kind,
                    "OPERATIONAL_ACTION",
                )

                self.assertEqual(
                    result.action,
                    "open",
                )

                self.assertEqual(
                    result.target,
                    target,
                )

                self.assertNotIn(
                    target,
                    result.excluded_targets,
                )

                self.assertGreaterEqual(
                    result.confidence,
                    0.95,
                )

    def test_compound_requires_known_app_catalogue(
        self,
    ):
        result = resolve_context_clauses(
            "Nao abras o Spotify, abre o Brave."
        )

        self.assertEqual(
            result.kind,
            "NONE",
        )

    def test_negative_only_does_not_become_positive(
        self,
    ):
        result = resolve_context_clauses(
            "Nao abras o Spotify.",
            app_aliases=APP_ALIASES,
        )

        self.assertEqual(
            result.kind,
            "NONE",
        )

    def test_non_app_preference_is_not_application(
        self,
    ):
        result = resolve_context_clauses(
            "Nao quero cafe; quero agua.",
            app_aliases=APP_ALIASES,
        )

        self.assertEqual(
            result.kind,
            "NONE",
        )

    def test_semantic_compound_with_catalogue(
        self,
    ):
        request = resolve_semantic_request(
            "Nao abras o Spotify, abre o Brave.",
            app_aliases=APP_ALIASES,
        )

        self.assertEqual(
            request.intent,
            "OPERATIONAL_ACTION",
        )

        self.assertEqual(
            request.action,
            "open",
        )

        self.assertEqual(
            request.target,
            "brave",
        )

        self.assertEqual(
            request.preferred_tool,
            "open_application",
        )

        self.assertEqual(
            request.as_dict()["tool_arguments"],
            {
                "app_name": "brave",
            },
        )

    def test_semantic_compound_without_catalogue_stays_closed(
        self,
    ):
        request = resolve_semantic_request(
            "Nao abras o Spotify, abre o Brave."
        )

        self.assertEqual(
            request.intent,
            "UNKNOWN",
        )

        self.assertFalse(
            request.requires_tool
        )

        self.assertIsNone(
            request.preferred_tool
        )

    def test_semantic_contextual_self_state(
        self,
    ):
        recent = [
            {
                "user": "Como te sentes?",
                "assistant": "Estou focada.",
                "route": (
                    "FAST/self_state_affect"
                ),
            }
        ]

        request = resolve_semantic_request(
            "Em que?",
            recent_turns=recent,
        )

        self.assertEqual(
            request.intent,
            "SELF_STATE",
        )

        self.assertEqual(
            request.subject,
            "JARVIS",
        )

        self.assertEqual(
            request.referent,
            "jarvis_self_state",
        )

        self.assertEqual(
            request.preferred_tool,
            "get_synthetic_self_state",
        )

    def test_cli_supplies_runtime_context_and_app_catalogue(
        self,
    ):
        source = (
            Path("jarvis_core/cli.py")
            .read_text(
                encoding="utf-8"
            )
        )

        self.assertIn(
            "def semantic_context_inputs():",
            source,
        )

        self.assertIn(
            "persistent_context.recent(4)",
            source,
        )

        self.assertIn(
            "apps.list_apps()",
            source,
        )

        call_start = source.index(
            "structured_request = "
            "resolve_semantic_request("
        )

        call_end = source.index(
            "\n\n        events.emit(",
            call_start,
        )

        semantic_call = source[
            call_start:call_end
        ]

        self.assertIn(
            "recent_turns=semantic_recent_turns",
            semantic_call,
        )

        self.assertIn(
            "app_aliases=semantic_app_aliases",
            semantic_call,
        )



    def test_social_followups_require_social_context(
        self,
    ):
        recent = [
            {
                "user": "Provoca-me",
                "assistant": (
                    "Interacao social ativa."
                ),
                "route": (
                    "FAST/social_interaction"
                ),
            }
        ]

        cases = (
            "Mais.",
            "Continua.",
            "Mais subtil.",
            "Agora mais provocadora.",
            "Se mais atrevida.",
            "Agora surpreende-me.",
            "Quero diversao.",
            "Que tipo de diversao tens em mente?",
        )

        for text in cases:
            with self.subTest(text=text):
                request = resolve_semantic_request(
                    text,
                    recent_turns=recent,
                    app_aliases=APP_ALIASES,
                )

                self.assertEqual(
                    request.intent,
                    "SOCIAL_INTERACTION",
                )

                self.assertFalse(
                    request.requires_tool
                )

                self.assertIsNone(
                    request.preferred_tool
                )

    def test_social_followup_without_context_fails_closed(
        self,
    ):
        request = resolve_semantic_request(
            "Mais.",
            app_aliases=APP_ALIASES,
        )

        self.assertEqual(
            request.intent,
            "UNKNOWN",
        )

        self.assertFalse(
            request.requires_tool
        )

    def test_known_app_execute_and_abre_me_resolve_open(
        self,
    ):
        cases = (
            "Executa o Brave",
            "Abre-me o Brave",
        )

        for text in cases:
            with self.subTest(text=text):
                request = resolve_semantic_request(
                    text,
                    app_aliases=APP_ALIASES,
                )

                self.assertEqual(
                    request.intent,
                    "OPERATIONAL_ACTION",
                )

                self.assertEqual(
                    request.action,
                    "open",
                )

                self.assertEqual(
                    request.target,
                    "brave",
                )

                self.assertEqual(
                    request.preferred_tool,
                    "open_application",
                )

                self.assertEqual(
                    request.as_dict()[
                        "tool_arguments"
                    ],
                    {
                        "app_name": "brave",
                    },
                )

    def test_ambiguous_operational_referents_fail_closed(
        self,
    ):
        cases = (
            "Abre isso.",
            "Fecha isso.",
            "Executa aquilo.",
        )

        for text in cases:
            with self.subTest(text=text):
                request = resolve_semantic_request(
                    text,
                    app_aliases=APP_ALIASES,
                )

                self.assertEqual(
                    request.intent,
                    "UNKNOWN",
                )

                self.assertFalse(
                    request.requires_tool
                )

                self.assertIsNone(
                    request.preferred_tool
                )

                self.assertIsNone(
                    request.target
                )

    def test_owner_subject_questions_are_owner(
        self,
    ):
        cases = (
            "Qual e a minha profissao?",
            "Quais sao os meus objetivos?",
            "O que eu prefiro?",
            "Qual e o meu carro?",
            "Onde vivo?",
            "O que sabes sobre mim?",
            "A que horas prefiro trabalhar?",
            "Prefiro trabalhar de manha ou a noite?",
        )

        for text in cases:
            with self.subTest(text=text):
                request = resolve_semantic_request(
                    text,
                    app_aliases=APP_ALIASES,
                )

                self.assertEqual(
                    request.subject,
                    "OWNER",
                )

                self.assertFalse(
                    request.requires_tool
                )

    def test_jarvis_subject_questions_are_jarvis(
        self,
    ):
        cases = (
            "Qual e a tua profissao?",
            "Quais sao os teus objetivos?",
            "O que tu preferes?",
            "Qual e o teu carro?",
            "Onde vives?",
            "O que sabes sobre ti?",
        )

        for text in cases:
            with self.subTest(text=text):
                request = resolve_semantic_request(
                    text,
                    app_aliases=APP_ALIASES,
                )

                self.assertEqual(
                    request.subject,
                    "JARVIS",
                )

                self.assertFalse(
                    request.requires_tool
                )

    def test_routing_harness_checks_semantic_contract(
        self,
    ):
        source = (
            Path("tools/routing_dry_run.py")
            .read_text(
                encoding="utf-8"
            )
        )

        self.assertIn(
            "def semantic_expectation_failures(",
            source,
        )

        self.assertIn(
            "semantic_expectation_failures(",
            source,
        )

        self.assertIn(
            "semantic_call is not None",
            source,
        )

        self.assertIn(
            'category == "social_followup"',
            source,
        )


if __name__ == "__main__":
    unittest.main()
