import unittest

from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


class LearningGoalPermissionContractTests(
    unittest.TestCase
):
    def test_plain_learning_goal_is_local_only_and_does_not_request_web(
        self,
    ):
        text = (
            "Jarvis, quero que aprendas comportamento humano"
        )

        request = resolve_semantic_request(
            text,
            recent_turns=[],
            app_aliases={},
        )

        self.assertEqual(
            request.intent,
            "OPERATIONAL_ACTION",
        )

        self.assertEqual(
            request.domain,
            "knowledge",
        )

        self.assertEqual(
            request.subject,
            "JARVIS",
        )

        self.assertEqual(
            request.action,
            "record_learning_goal",
        )

        self.assertTrue(
            request.requires_tool
        )

        self.assertEqual(
            request.preferred_tool,
            "record_jarvis_learning_goal",
        )

        self.assertNotEqual(
            request.preferred_tool,
            "execute_authorized_external_learning",
        )

        args = dict(
            request.tool_arguments
        )

        self.assertEqual(
            args.get("source_text"),
            text,
        )

        self.assertTrue(
            str(
                args.get("topic")
                or ""
            ).strip()
        )

        self.assertNotIn(
            "direct_user_authority",
            args,
        )

        self.assertNotIn(
            "authorization_token",
            args,
        )

        self.assertNotIn(
            "approved_grant",
            args,
        )


if __name__ == "__main__":
    unittest.main()
