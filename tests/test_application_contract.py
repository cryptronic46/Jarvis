from __future__ import annotations

from pathlib import Path
import ast
import unittest

from jarvis_core.application import (
    JarvisApplication,
)
from jarvis_core.runtime import (
    ProcessRequestResult,
)


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def process_request(
        self,
        user_text,
        *,
        source="terminal",
    ):
        self.calls.append(
            {
                "user_text": user_text,
                "source": source,
            }
        )

        return ProcessRequestResult(
            answer="ok",
            route="LOCAL/test",
            elapsed_ms=7,
            hybrid=None,
        )


class FakeAutonomy:
    def __init__(self):
        self.calls = []

    def record_direct_authorization(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        return {
            "ok": True,
            "authorized": True,
            "execution_token":
                "TOKEN-123",
        }


class FakeKaliBridge:
    def __init__(self):
        self.open_calls = []

    def build_security_session_scope(
        self,
        *,
        target,
        profiles,
        ports,
        scope,
    ):
        return {
            "ok": True,
            "payload": {
                "target": target,
                "profiles": list(
                    profiles
                ),
                "ports": ports,
                "scope": scope,
            },
        }

    def open_security_session(
        self,
        **kwargs,
    ):
        self.open_calls.append(
            kwargs
        )

        return {
            "ok": True,
        }


class FakeCyberKnowledge:
    def __init__(self):
        self.calls = []

    def sync(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        return {
            "ok": True,
        }


class JarvisApplicationContractTests(
    unittest.TestCase
):
    def make_application(self):
        return JarvisApplication(
            runtime=FakeRuntime(),
            autonomy=FakeAutonomy(),
            kali_bridge=FakeKaliBridge(),
            cyber_knowledge=(
                FakeCyberKnowledge()
            ),
        )

    def test_process_request_delegates_to_single_runtime(
        self,
    ):
        app = self.make_application()

        result = app.process_request(
            "Ol?",
            source="web",
        )

        self.assertEqual(
            result.answer,
            "ok",
        )

        self.assertEqual(
            app.runtime.calls,
            [
                {
                    "user_text": "Ol?",
                    "source": "web",
                }
            ],
        )

    def test_kali_action_remains_owner_authorized(
        self,
    ):
        app = self.make_application()

        result = (
            app.open_owner_kali_session(
                target="192.168.1.10",
                profiles=[
                    "safe",
                ],
                ports=[
                    22,
                ],
                scope="lab",
                source_text="autoriza",
            )
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            app.autonomy.calls[
                0
            ][
                "capability"
            ],
            "kali_security_session",
        )

        self.assertEqual(
            app.kali_bridge.open_calls[
                0
            ][
                "execution_token"
            ],
            "TOKEN-123",
        )

    def test_cyber_sync_remains_owner_authorized(
        self,
    ):
        app = self.make_application()

        result = (
            app.owner_authorized_cyber_sync(
                full=True,
                source_id="official",
                source_text="autoriza",
            )
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            app.autonomy.calls[
                0
            ][
                "capability"
            ],
            "external_learning",
        )

        self.assertEqual(
            app.cyber_knowledge.calls[
                0
            ][
                "execution_token"
            ],
            "TOKEN-123",
        )

    def test_cli_uses_application_boundary(
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
                "application = "
                "JarvisApplication("
            ),
            1,
        )

        self.assertIn(
            "application.process_request(",
            main_source,
        )

        self.assertNotIn(
            "def open_owner_kali_session(",
            main_source,
        )

        self.assertNotIn(
            "def owner_authorized_cyber_sync(",
            main_source,
        )


if __name__ == "__main__":
    unittest.main()
