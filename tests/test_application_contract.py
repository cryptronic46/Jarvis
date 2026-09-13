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


class FakeSettings:
    performance_release_llm_on_pressure = True
    performance_warmup_delay_seconds = 0.0
    background_warmup = False
    ollama_release_on_shutdown = True


class FakeEvents:
    def __init__(self):
        self.rows = []

    def emit(
        self,
        name,
        **payload,
    ):
        self.rows.append(
            (name, payload)
        )


class FakeBrain:
    def __init__(self):
        self.release_model_calls = []
        self.release_all_calls = []
        self.warmup_calls = 0

    def release_model(
        self,
        *,
        reason,
    ):
        self.release_model_calls.append(
            reason
        )
        return {"ok": True}

    def release_all_models(
        self,
        **kwargs,
    ):
        self.release_all_calls.append(
            kwargs
        )

    def warmup(self):
        self.warmup_calls += 1


class FakeService:
    def __init__(self):
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


class FakePerformance(FakeService):
    def __init__(self):
        super().__init__()
        self.callback = None

    def start(
        self,
        *,
        on_sustained_pressure,
    ):
        self.starts += 1
        self.callback = on_sustained_pressure

    def should_warm_llm(self):
        return False

    def pressure(self):
        return {"state": "ok"}


class FakeRequestLock:
    def __init__(self):
        self.enters = 0
        self.exits = 0

    def __enter__(self):
        self.enters += 1
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        self.exits += 1
        return False


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
            settings=FakeSettings(),
            events=FakeEvents(),
            brain=FakeBrain(),
            telemetry=FakeService(),
            performance=FakePerformance(),
            activity_trace=FakeService(),
            request_lock=FakeRequestLock(),
        )

    def test_runtime_lifecycle_is_application_owned(
        self,
    ):
        app = self.make_application()

        app.start_runtime_services()

        self.assertEqual(
            app.activity_trace.starts,
            1,
        )
        self.assertEqual(
            app.telemetry.starts,
            1,
        )
        self.assertEqual(
            app.performance.starts,
            1,
        )

        app.performance.callback(
            {"cpu": 95}
        )

        self.assertEqual(
            app.brain.release_model_calls,
            ["sustained_resource_pressure"],
        )

        app.stop_activity_trace()
        app.release_models_on_shutdown()
        app.stop_runtime_services()

        self.assertEqual(
            app.activity_trace.stops,
            1,
        )
        self.assertEqual(
            app.performance.stops,
            1,
        )
        self.assertEqual(
            app.telemetry.stops,
            1,
        )

        self.assertEqual(
            app.brain.release_all_calls,
            [
                {
                    "reason":
                        "jarvis_shutdown",
                    "include_configured":
                        True,
                }
            ],
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

        self.assertEqual(
            app.request_lock.enters,
            1,
        )

        self.assertEqual(
            app.request_lock.exits,
            1,
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
                "bootstrap = build_application()"
            ),
            1,
        )

        self.assertIn(
            "application = bootstrap.application",
            main_source,
        )

        self.assertNotIn(
            "JarvisApplication(",
            main_source,
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

        self.assertIn(
            "application.start_runtime_services()",
            main_source,
        )
        self.assertIn(
            "application.stop_activity_trace()",
            main_source,
        )
        self.assertIn(
            "application.release_models_on_shutdown()",
            main_source,
        )
        self.assertIn(
            "application.stop_runtime_services()",
            main_source,
        )

        # Manual OWNER maintenance remains a terminal capability.
        self.assertIn(
            'reason="manual_release"',
            main_source,
        )

        # Only shutdown ownership moves into JarvisApplication.
        self.assertNotIn(
            'reason="jarvis_shutdown"',
            main_source,
        )


if __name__ == "__main__":
    unittest.main()
