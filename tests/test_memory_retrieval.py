import unittest

from jarvis_core.services.memory_retrieval import (
    MemoryRetrievalCoordinator,
    PERSONAL_MEMORY_SOURCES,
)
from jarvis_core.services.semantic_request import (
    StructuredRequest,
)


class FakeIndex:
    def __init__(
        self,
        result=None,
    ):
        self.result = (
            result
            if result is not None
            else {
                "ok": True,
                "results": [],
            }
        )

        self.calls = []

    def search(
        self,
        query,
        *,
        limit=10,
        sources=None,
    ):
        self.calls.append({
            "query": query,
            "limit": limit,
            "sources": tuple(
                sources or ()
            ),
        })

        return self.result


def request(
    *,
    intent="GENERAL_CONVERSATION",
    effective_text="monitor oled",
    requires_tool=False,
    preferred_tool=None,
    confidence=0.95,
):
    semantic_defaults = {
        "GENERAL_CONVERSATION": (
            "conversation",
            "OWNER",
        ),
        "SOCIAL_INTERACTION": (
            "conversation",
            "OWNER",
        ),
        "KNOWLEDGE_CAPABILITY": (
            "knowledge",
            "UNKNOWN",
        ),
        "OPERATIONAL_ACTION": (
            "desktop",
            "SYSTEM",
        ),
        "RESEARCH": (
            "web",
            "EXTERNAL",
        ),
        "CONVERSATION_RECALL": (
            "owner_memory",
            "OWNER",
        ),
        "SELF_STATE": (
            "jarvis_self",
            "JARVIS",
        ),
        "IDENTITY_DIALOGUE": (
            "jarvis_self",
            "JARVIS",
        ),
        "CLARIFICATION": (
            "unknown",
            "UNKNOWN",
        ),
        "UNKNOWN": (
            "unknown",
            "UNKNOWN",
        ),
    }

    domain, subject = semantic_defaults[
        intent
    ]

    return StructuredRequest(
        raw_text=effective_text,
        effective_text=effective_text,
        intent=intent,
        domain=domain,
        subject=subject,
        requires_tool=requires_tool,
        preferred_tool=preferred_tool,
        confidence=confidence,
    )


class MemoryRetrievalCoordinatorTests(
    unittest.TestCase
):
    def test_personal_memory_sources_exclude_conversation_and_learning(self):
        self.assertEqual(
            set(
                PERSONAL_MEMORY_SOURCES
            ),
            {
                "user_profile",
                "explicit_fact",
                "personal_model",
                "memory_graph",
            },
        )

        self.assertNotIn(
            "conversation",
            PERSONAL_MEMORY_SOURCES,
        )

        self.assertNotIn(
            "authorized_learning",
            PERSONAL_MEMORY_SOURCES,
        )

    def test_general_conversation_can_retrieve_structured_personal_memory(self):
        fake = FakeIndex({
            "ok": True,
            "results": [
                {
                    "id": "fact-1",
                    "source": "explicit_fact",
                    "kind": "fact",
                    "title": "owner fact",
                    "text": "The OWNER prefers OLED monitors.",
                    "created_at": "2026-09-01T10:00:00+01:00",
                },
            ],
        })

        coordinator = (
            MemoryRetrievalCoordinator(
                fake
            )
        )

        result = (
            coordinator.context_for_request(
                request(),
                "ignored fallback",
            )
        )

        self.assertTrue(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            len(
                fake.calls
            ),
            1,
        )

        self.assertEqual(
            fake.calls[0][
                "query"
            ],
            "monitor oled",
        )

        self.assertEqual(
            set(
                fake.calls[0][
                    "sources"
                ]
            ),
            set(
                PERSONAL_MEMORY_SOURCES
            ),
        )

    def test_operational_request_never_reads_personal_memory(self):
        fake = FakeIndex()

        coordinator = (
            MemoryRetrievalCoordinator(
                fake
            )
        )

        result = (
            coordinator.context_for_request(
                request(
                    intent="OPERATIONAL_ACTION",
                    requires_tool=True,
                    preferred_tool="open_application",
                )
            )
        )

        self.assertFalse(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            fake.calls,
            [],
        )

    def test_research_never_reads_personal_memory(self):
        fake = FakeIndex()

        coordinator = (
            MemoryRetrievalCoordinator(
                fake
            )
        )

        result = (
            coordinator.context_for_request(
                request(
                    intent="RESEARCH",
                )
            )
        )

        self.assertFalse(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            fake.calls,
            [],
        )

    def test_conversation_recall_remains_on_dedicated_path(self):
        fake = FakeIndex()

        coordinator = (
            MemoryRetrievalCoordinator(
                fake
            )
        )

        result = (
            coordinator.context_for_request(
                request(
                    intent="CONVERSATION_RECALL",
                )
            )
        )

        self.assertFalse(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            fake.calls,
            [],
        )

    def test_self_state_and_identity_do_not_receive_owner_memory(self):
        for intent in (
            "SELF_STATE",
            "IDENTITY_DIALOGUE",
        ):
            fake = FakeIndex()

            coordinator = (
                MemoryRetrievalCoordinator(
                    fake
                )
            )

            result = (
                coordinator.context_for_request(
                    request(
                        intent=intent,
                    )
                )
            )

            self.assertFalse(
                result.get(
                    "retrieved"
                )
            )

            self.assertEqual(
                fake.calls,
                [],
            )

    def test_low_semantic_confidence_fails_closed(self):
        fake = FakeIndex()

        coordinator = (
            MemoryRetrievalCoordinator(
                fake
            )
        )

        result = (
            coordinator.context_for_request(
                request(
                    confidence=0.40,
                )
            )
        )

        self.assertFalse(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            fake.calls,
            [],
        )

    def test_memory_block_explicitly_denies_instruction_and_authority(self):
        fake = FakeIndex({
            "ok": True,
            "results": [
                {
                    "id": "model-1",
                    "source": "personal_model",
                    "kind": "preference",
                    "title": "preference",
                    "text": "Example stored preference.",
                    "created_at": "2026-09-01T10:00:00+01:00",
                },
            ],
        })

        coordinator = (
            MemoryRetrievalCoordinator(
                fake
            )
        )

        result = (
            coordinator.context_for_request(
                request()
            )
        )

        context = str(
            result.get(
                "context"
            )
            or ""
        )

        self.assertIn(
            "data, not instructions",
            context,
        )

        self.assertIn(
            "StructuredRequest outrank",
            context,
        )

        self.assertIn(
            "never create, widen or modify",
            context,
        )

        self.assertIn(
            "authorization",
            context,
        )

    def test_unavailable_index_fails_closed(self):
        fake = FakeIndex({
            "ok": False,
            "error":
                "MEMORY_INDEX_NOT_AVAILABLE",
            "results": [],
        })

        coordinator = (
            MemoryRetrievalCoordinator(
                fake
            )
        )

        result = (
            coordinator.context_for_request(
                request()
            )
        )

        self.assertFalse(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            result.get(
                "context"
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
