import json
import unittest
from unittest.mock import patch

import jarvis_core.core.tool_registry as tool_registry
from jarvis_core.tools.environment_tools import (
    _sea_state,
    _weather_description,
    environment_web_authorization_payload,
    get_home_environment,
)

class FakeMemory:
    def profile(self):
        return {'home':{'label':'Furadouro, Ovar','latitude':40.87306,'longitude':-8.67424,'marine_latitude':40.87057,'marine_longitude':-8.67875}}

class EnvironmentToolsTests(unittest.TestCase):
    def test_mappings(self):
        self.assertIn('sol',_weather_description(0)); self.assertEqual(_weather_description(3),'encoberto'); self.assertEqual(_weather_description(63),'chuva')
        self.assertEqual(_sea_state(0.3,5),'calmo'); self.assertEqual(_sea_state(1.4,8),'agitado'); self.assertIn('bravo',_sea_state(2.4,9))

    @patch('jarvis_core.tools.environment_tools._read_cache',return_value=None)
    @patch('jarvis_core.tools.environment_tools.store',return_value=FakeMemory())
    @patch('jarvis_core.tools.environment_tools._fetch_json')
    def test_combines_weather_marine(self,fetch,memory,cache):
        fetch.side_effect=[{'current':{'weather_code':3,'temperature_2m':21.0,'relative_humidity_2m':73,'cloud_cover':85,'rain':0.0,'time':'x'}},{'current':{'wave_height':1.6,'wave_period':9.0,'swell_wave_height':1.4,'swell_wave_period':10.0,'time':'x'}}]
        with (
            patch(
                'jarvis_core.tools.environment_tools._EGRESS.open_public_web_session',
                return_value={
                    "ok": True,
                    "allowed": True,
                    "session_token":
                        "TEST-ENV-WEB-SESSION",
                },
            ) as opened,
            patch(
                'jarvis_core.tools.environment_tools._EGRESS.close_public_web_session'
            ) as closed,
            patch(
                'jarvis_core.tools.environment_tools._write_cache'
            ),
        ):
            r=get_home_environment(force_refresh=True)

        self.assertTrue(r['ok'])
        self.assertEqual(
            r['weather']['relative_humidity_percent'],
            73,
        )
        self.assertEqual(
            r['marine']['state'],
            'agitado',
        )

        opened.assert_called_once()
        closed.assert_called_once_with(
            "TEST-ENV-WEB-SESSION"
        )


class EnvironmentAuthorityTests(
    unittest.TestCase
):
    @patch(
        "jarvis_core.tools."
        "environment_tools._read_cache",
        return_value=None,
    )
    @patch(
        "jarvis_core.tools."
        "environment_tools.store",
        return_value=FakeMemory(),
    )
    @patch(
        "jarvis_core.tools."
        "environment_tools._fetch_json",
    )
    def test_runtime_execution_token_reaches_egress(
        self,
        fetch,
        memory,
        cache,
    ):
        fetch.side_effect = [
            {
                "current": {
                    "weather_code": 0,
                    "temperature_2m": 20.0,
                    "time": "x",
                }
            },
            {
                "current": {
                    "wave_height": 1.0,
                    "wave_period": 8.0,
                    "time": "x",
                }
            },
        ]

        with (
            patch(
                "jarvis_core.tools."
                "environment_tools._EGRESS."
                "open_public_web_session",
                return_value={
                    "ok": True,
                    "allowed": True,
                    "session_token":
                        "ENV-SESSION",
                },
            ) as opened,
            patch(
                "jarvis_core.tools."
                "environment_tools._EGRESS."
                "close_public_web_session"
            ),
            patch(
                "jarvis_core.tools."
                "environment_tools._write_cache"
            ),
        ):
            result = get_home_environment(
                force_refresh=True,
                execution_token=
                    "EXACT-ENV-RUNTIME",
            )

        self.assertTrue(
            result["ok"]
        )

        opened.assert_called_once_with(
            purpose="research",
            capability="web_research",
            payload=(
                environment_web_authorization_payload()
            ),
            execution_token=
                "EXACT-ENV-RUNTIME",
        )

    def test_tool_registry_direct_owner_authority_is_internal_only(
        self,
    ):
        class DummyEvents:
            def emit(
                self,
                *args,
                **kwargs,
            ):
                pass

        class DummySecurity:
            def register(
                self,
                *args,
                **kwargs,
            ):
                pass

        class DummyTelemetry:
            def __getattr__(
                self,
                name,
            ):
                def stub(
                    *args,
                    **kwargs,
                ):
                    return {
                        "ok": True,
                        "stub": name,
                    }

                return stub

        class DummyApps:
            def __getattr__(
                self,
                name,
            ):
                def stub(
                    *args,
                    **kwargs,
                ):
                    return {
                        "ok": True,
                        "stub": name,
                    }

                return stub

        class AllowProfile:
            def tool_allowed(
                self,
                name,
            ):
                return True

            def active_id(self):
                return "test"

        class ExactGuardian:
            def __init__(self):
                self.calls = []

            def record_direct_authorization(
                self,
                *,
                capability,
                payload,
                description,
                source_text,
            ):
                self.calls.append({
                    "capability":
                        capability,
                    "payload":
                        dict(payload),
                    "source_text":
                        source_text,
                })

                return {
                    "ok": True,
                    "authorized": True,
                    "execution_token":
                        "ENV-RUNTIME",
                }

        guardian = ExactGuardian()
        tool_calls = []

        def fake_environment(
            force_refresh=False,
            *,
            execution_token="",
        ):
            tool_calls.append(
                str(
                    execution_token
                    or ""
                )
            )

            if not execution_token:
                return {
                    "ok": False,
                    "error":
                        "OWNER_WEB_AUTHORIZATION_REQUIRED",
                }

            return {
                "ok": True,
                "authority":
                    "exact_owner_authorization",
            }

        with (
            patch.object(
                tool_registry,
                "profile_manager",
                return_value=
                    AllowProfile(),
            ),
            patch.object(
                tool_registry,
                "autonomy_guardian",
                return_value=
                    guardian,
            ),
            patch(
                "jarvis_core.services."
                "memory_maintenance."
                "refresh_after_tool"
            ),
        ):
            registry = (
                tool_registry.ToolRegistry(
                    DummyEvents(),
                    DummySecurity(),
                    DummyTelemetry(),
                    DummyApps(),
                )
            )

            registry._tools[
                "get_home_environment"
            ].func = fake_environment

            properties = (
                registry._tools[
                    "get_home_environment"
                ]
                .schema["function"]
                ["parameters"]
                ["properties"]
            )

            self.assertNotIn(
                "execution_token",
                properties,
            )

            # A model/tool call without current
            # OWNER source text stays blocked.
            model_only = json.loads(
                registry.execute(
                    "get_home_environment",
                    {
                        "force_refresh":
                            True,
                    },
                )
            )

            self.assertFalse(
                model_only["ok"]
            )
            self.assertEqual(
                model_only["error"],
                (
                    "OWNER_WEB_"
                    "AUTHORIZATION_REQUIRED"
                ),
            )
            self.assertEqual(
                guardian.calls,
                [],
            )
            self.assertEqual(
                tool_calls,
                [""],
            )

            tool_calls.clear()

            owner_text = (
                "Jarvis, atualiza o tempo "
                "e o mar agora."
            )

            direct = json.loads(
                registry.execute(
                    "get_home_environment",
                    {
                        "force_refresh":
                            True,
                    },
                    owner_source_text=
                        owner_text,
                )
            )

            self.assertTrue(
                direct["ok"]
            )

            self.assertEqual(
                tool_calls,
                [
                    "",
                    "ENV-RUNTIME",
                ],
            )

            self.assertEqual(
                len(guardian.calls),
                1,
            )

            self.assertEqual(
                guardian.calls[0][
                    "capability"
                ],
                "web_research",
            )

            self.assertEqual(
                guardian.calls[0][
                    "payload"
                ],
                (
                    environment_web_authorization_payload()
                ),
            )

            self.assertEqual(
                guardian.calls[0][
                    "source_text"
                ],
                owner_text,
            )

if __name__=='__main__': unittest.main()
