from __future__ import annotations

from dataclasses import fields
from pathlib import Path
import ast
import unittest

from jarvis_core.bootstrap import (
    ApplicationBootstrapResult,
    JarvisCoreContext,
)


EXPECTED_CONTEXT_FIELDS = (
    "memory",
    "profiles",
    "user_address",
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
    def test_core_context_is_internal_and_transport_free(
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
            name: (
                "Senhor"
                if name == "user_address"
                else object()
            )
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

    def test_build_application_contract_is_process_singleton(
        self,
    ):
        source = Path(
            "jarvis_core/bootstrap.py"
        ).read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            source
        )

        build = next(
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "build_application"
        )

        build_source = (
            ast.get_source_segment(
                source,
                build,
            )
            or ""
        )

        self.assertIn(
            "global _BOOTSTRAP_RESULT",
            build_source,
        )

        self.assertIn(
            "with _BOOTSTRAP_LOCK:",
            build_source,
        )

        self.assertIn(
            "if _BOOTSTRAP_RESULT is not None:",
            build_source,
        )

        self.assertIn(
            "_BOOTSTRAP_RESULT = result",
            build_source,
        )

        self.assertIn(
            "JarvisRuntime(",
            build_source,
        )

        self.assertIn(
            "JarvisApplication(",
            build_source,
        )

    def test_cli_constructs_core_only_through_bootstrap(
        self,
    ):
        source = Path(
            "jarvis_core/cli.py"
        ).read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            source
        )

        main = next(
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "main"
        )

        main_source = (
            ast.get_source_segment(
                source,
                main,
            )
            or ""
        )

        self.assertEqual(
            main_source.count(
                "bootstrap = build_application()"
            ),
            1,
        )

        self.assertIn(
            "application = bootstrap.application",
            main_source,
        )

        self.assertIn(
            "context = bootstrap.context",
            main_source,
        )

        for forbidden in (
            "JarvisApplication(",
            "JarvisRuntime(",
            "CanonicalMemoryStore(",
            "JarvisBrain(",
            "Settings.load(",
        ):
            self.assertNotIn(
                forbidden,
                main_source,
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


if __name__ == "__main__":
    unittest.main()
