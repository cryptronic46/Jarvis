import unittest

from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


class DirectMemoryOrderTests(unittest.TestCase):
    def assert_semantic_memory_write(
        self,
        text,
        expected_fact,
    ):
        request = (
            resolve_semantic_request(
                text
            )
        )

        self.assertEqual(
            request.intent,
            "OPERATIONAL_ACTION",
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
            "remember_owner_fact",
        )

        self.assertEqual(
            request.target,
            "OWNER",
        )

        self.assertTrue(
            request.requires_tool
        )

        self.assertEqual(
            request.preferred_tool,
            "remember_user_fact",
        )

        self.assertEqual(
            request.as_dict()[
                "tool_arguments"
            ],
            {
                "fact": expected_fact,
                "category": "user_explicit",
            },
        )

        self.assertEqual(
            request.confidence,
            0.99,
        )

        self.assertFalse(
            request.epistemic_learning_eligible
        )

    def test_memoriza_natural_fact_without_que(
        self,
    ):
        self.assert_semantic_memory_write(
            (
                "Jarvis, memoriza o nome da minha "
                "mulher: Ana Isa Guimar?es Lopes, "
                "e a data de nascimento: "
                "27 de Fevereiro de 1987."
            ),
            (
                "o nome da minha mulher: "
                "Ana Isa Guimar?es Lopes, "
                "e a data de nascimento: "
                "27 de Fevereiro de 1987"
            ),
        )

    def test_quero_que_memorizes_natural_fact(
        self,
    ):
        self.assert_semantic_memory_write(
            (
                "Quero que memorizes o nome da "
                "minha mulher e a data de "
                "nascimento dela."
            ),
            (
                "o nome da minha mulher e a "
                "data de nascimento dela"
            ),
        )

    def test_bare_memoriza_isso_is_not_stored_as_literal_fact(
        self,
    ):
        request = (
            resolve_semantic_request(
                "Memoriza isso."
            )
        )

        is_memory_write = (
            request.intent
            == "OPERATIONAL_ACTION"
            and request.domain
            == "owner_memory"
            and request.action
            == "remember_owner_fact"
            and request.preferred_tool
            == "remember_user_fact"
        )

        self.assertFalse(
            is_memory_write
        )


if __name__ == "__main__":
    unittest.main()
