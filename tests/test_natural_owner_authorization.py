import unittest

from jarvis_core.services.autonomy import (
    parse_direct_external_learning_order,
    parse_learning_goal,
)


class NaturalOwnerAuthorizationTests(unittest.TestCase):
    def test_exact_user_sentence_is_direct_authority(self):
        result = parse_direct_external_learning_order(
            "Tens a minha autorização para aprender sobre comportamento humano através da internet"
        )
        self.assertIsNotNone(result)
        self.assertEqual(
            result["topic"],
            "comportamento humano",
        )
        self.assertTrue(
            result["direct_user_authority"]
        )
        self.assertEqual(
            result["scope"],
            "single_research_session",
        )

    def test_autorizo_te_variant(self):
        result = parse_direct_external_learning_order(
            "Autorizo-te a aprender sobre psicologia social pela internet."
        )
        self.assertIsNotNone(result)
        self.assertEqual(
            result["topic"],
            "psicologia social",
        )

    def test_direct_research_and_learn_variant(self):
        result = parse_direct_external_learning_order(
            "Pesquisa na internet e aprende sobre linguagem corporal."
        )
        self.assertIsNotNone(result)
        self.assertEqual(
            result["topic"],
            "linguagem corporal",
        )

    def test_learning_goal_without_internet_is_not_direct_web_authority(self):
        direct = parse_direct_external_learning_order(
            "Jarvis, eu quero que tu aprendas tudo sobre comportamento humano!"
        )
        self.assertIsNone(direct)

        goal = parse_learning_goal(
            "Jarvis, eu quero que tu aprendas tudo sobre comportamento humano!"
        )
        self.assertIsNotNone(goal)
        self.assertEqual(
            goal["topic"],
            "comportamento humano",
        )

    def test_generic_chat_is_not_authority(self):
        self.assertIsNone(
            parse_direct_external_learning_order(
                "Bom dia Jarvis"
            )
        )
        self.assertIsNone(
            parse_learning_goal(
                "Bom dia Jarvis"
            )
        )


if __name__ == "__main__":
    unittest.main()
