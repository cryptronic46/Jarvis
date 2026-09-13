from __future__ import annotations

from dataclasses import fields
from pathlib import Path
import unittest

from jarvis_core.bootstrap import (
    ApplicationBootstrapResult,
    JarvisCoreContext,
)


EXPECTED_CONTEXT_FIELDS = (
    "memory",
    "profiles",
    "agenda",
    "routines",
    "inventory",
    "integrations",
    "book_library",
    "cognition",
    "self_engine",
    "security",
    "apps",
    "cyber_range",
    "tools",
    "memory1_store",
    "research_engine",
    "skill_context",
    "skills",
    "hybrid_brain",
    "command_lock",
    "silence_latch",
)


class BootstrapContractTests(
    unittest.TestCase
):
    def test_core_context_is_narrow_and_has_no_transport_state(
        self,
    ):
        names = tuple(
            field.name
            for field in fields(
                JarvisCoreContext
            )
        )

        self.assertEqual(
            names,
            EXPECTED_CONTEXT_FIELDS,
        )

        forbidden = {
            "debug_terminal",
            "runtime",
            "turn_runtime",
            "settings",
            "events",
            "brain",
            "telemetry",
            "performance",
            "activity_trace",
            "autonomy",
            "kali_bridge",
            "cyber_knowledge",
            "persistent_context",
            "local_files",
            "relational_presence_store",
            "memory1_owner_bindings",
            "memory1_owner_id",
            "memory1_qwen_model",
            "memory1_matcher",
            "memory1_adapter",
            "fast_router",
        }

        self.assertTrue(
            forbidden.isdisjoint(
                names
            )
        )

    def test_bootstrap_result_separates_application_and_context(
        self,
    ):
        values = {
            name: object()
            for name
            in EXPECTED_CONTEXT_FIELDS
        }

        context = JarvisCoreContext(
            **values
        )

        application = object()

        result = (
            ApplicationBootstrapResult(
                application=application,
                context=context,
            )
        )

        self.assertIs(
            result.application,
            application,
        )

        self.assertIs(
            result.context,
            context,
        )

    def test_cli_no_longer_reaches_into_runtime_for_semantic_context(
        self,
    ):
        source = Path(
            "jarvis_core/cli.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "application.semantic_context_inputs()",
            source,
        )

        self.assertNotIn(
            "turn_runtime.semantic_context_inputs()",
            source,
        )

    def test_application_owns_semantic_context_seam(
        self,
    ):
        source = Path(
            "jarvis_core/application.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "def semantic_context_inputs(",
            source,
        )

        self.assertIn(
            ".semantic_context_inputs()",
            source,
        )


if __name__ == "__main__":
    unittest.main()
