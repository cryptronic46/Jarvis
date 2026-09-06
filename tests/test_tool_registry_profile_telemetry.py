import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import jarvis_core.core.tool_registry as tool_registry_module
from jarvis_core.core.tool_registry import ToolRegistry


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append((name, payload))


class _Profile:
    def tool_allowed(self, name):
        return False

    def active_id(self):
        return "restricted-test-profile"


class _Guardian:
    def __init__(self, result):
        self.result = dict(result)
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(dict(kwargs))
        return dict(self.result)


class ToolRegistryProfileTelemetryTests(unittest.TestCase):
    def _registry(self):
        events = _Events()
        registry = ToolRegistry.__new__(ToolRegistry)

        registry.events = events
        registry.security = Mock()
        registry.telemetry = Mock()
        registry.apps = Mock()
        registry.request_started_at = None

        func = Mock(
            return_value={
                "ok": False,
                "error": "SYNTHETIC_TOOL_RESULT",
            }
        )

        # execute() only needs these attributes for this focused gate test.
        # A plain non-critical/non-confirm risk value keeps all later security
        # branches out of scope without constructing the full builtin registry.
        tool = SimpleNamespace(
            name="telemetry_test_tool",
            description="synthetic profile telemetry test tool",
            func=func,
            schema={},
            risk="safe-test-risk",
        )

        registry._tools = {
            "telemetry_test_tool": tool,
        }

        registry._validate_arguments = Mock(
            return_value=(True, None)
        )

        return registry, events, func

    @staticmethod
    def _profile_block_events(events):
        return [
            payload
            for name, payload in events.rows
            if (
                name == "TOOL_BLOCKED"
                and payload.get("reason") == "profile_permission"
            )
        ]

    def test_allowed_owner_override_does_not_emit_profile_blocked(self):
        registry, events, func = self._registry()
        guardian = _Guardian(
            {
                "allowed": True,
                "pending": False,
            }
        )

        with (
            patch.object(
                tool_registry_module,
                "profile_manager",
                return_value=_Profile(),
            ),
            patch.object(
                tool_registry_module,
                "autonomy_guardian",
                return_value=guardian,
            ),
        ):
            result = json.loads(
                registry.execute(
                    "telemetry_test_tool",
                    {"value": 1},
                )
            )

        func.assert_called_once_with(value=1)
        self.assertEqual(
            result.get("error"),
            "SYNTHETIC_TOOL_RESULT",
        )

        self.assertEqual(
            self._profile_block_events(events),
            [],
            "authorized execution must not be logged as profile blocked",
        )

        names = [name for name, _ in events.rows]
        self.assertIn("TOOL_EXECUTING", names)
        self.assertIn("TOOL_FINISHED", names)

    def test_pending_owner_authorization_still_emits_profile_blocked(self):
        registry, events, func = self._registry()
        guardian = _Guardian(
            {
                "allowed": False,
                "pending": True,
                "token": "test-token",
                "message": "approval required",
            }
        )

        with (
            patch.object(
                tool_registry_module,
                "profile_manager",
                return_value=_Profile(),
            ),
            patch.object(
                tool_registry_module,
                "autonomy_guardian",
                return_value=guardian,
            ),
        ):
            result = json.loads(
                registry.execute(
                    "telemetry_test_tool",
                    {"value": 1},
                )
            )

        func.assert_not_called()

        self.assertEqual(
            result.get("error"),
            "OWNER_AUTHORIZATION_REQUIRED",
        )

        self.assertEqual(
            len(self._profile_block_events(events)),
            1,
        )

    def test_denied_profile_gate_still_emits_profile_blocked(self):
        registry, events, func = self._registry()
        guardian = _Guardian(
            {
                "allowed": False,
                "pending": False,
            }
        )

        with (
            patch.object(
                tool_registry_module,
                "profile_manager",
                return_value=_Profile(),
            ),
            patch.object(
                tool_registry_module,
                "autonomy_guardian",
                return_value=guardian,
            ),
        ):
            result = json.loads(
                registry.execute(
                    "telemetry_test_tool",
                    {"value": 1},
                )
            )

        func.assert_not_called()

        self.assertEqual(
            result.get("error"),
            "PROFILE_PERMISSION_DENIED",
        )

        self.assertEqual(
            len(self._profile_block_events(events)),
            1,
        )


if __name__ == "__main__":
    unittest.main()
