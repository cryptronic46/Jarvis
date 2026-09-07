import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from jarvis_core.services.companion_presence import (
    CompanionPresenceService,
)


class CompanionPresenceTests(
    unittest.TestCase
):
    def _service(
        self,
        planner,
        output,
        root,
    ):
        return CompanionPresenceService(
            planner,
            output,
            state_path=(
                Path(root)
                / "companion.json"
            ),
            enabled=True,
            check_interval_seconds=60,
            startup_delay_seconds=0,
            decision_cooldown_seconds=30,
            min_interval_minutes=2,
            idle_seconds=30,
            quiet_start_hour=0,
            quiet_end_hour=0,
            max_per_hour=2,
        )

    def _cognition(
        self,
        now=None,
    ):
        current = (
            now
            or datetime.now()
            .astimezone()
        )

        cognition = Mock()

        cognition.state.return_value = {
            "last_interaction_at": (
                current
                - timedelta(minutes=3)
            ).isoformat(),
        }

        cognition.time_boundaries.return_value = {
            "morning": "06:00",
            "afternoon": "12:00",
            "night": "20:00",
        }

        return cognition

    def test_model_can_choose_silence(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            planner = Mock(
                return_value={
                    "speak": False,
                    "tone": "neutral",
                    "reason": "silence",
                    "text": "",
                }
            )

            service = self._service(
                planner,
                Mock(),
                tmp,
            )

            relational = Mock()
            relational.snapshot.return_value = {
                "rapport": "warm",
            }

            with patch(
                (
                    "jarvis_core.services."
                    "companion_presence."
                    "personal_cognition"
                ),
                return_value=self._cognition(),
            ), patch(
                (
                    "jarvis_core.services."
                    "companion_presence."
                    "relational_presence"
                ),
                return_value=relational,
            ):
                result = (
                    service.evaluate_once()
                )

            self.assertTrue(
                result["eligible"]
            )
            self.assertFalse(
                result["spoken"]
            )

    def test_model_generated_message_is_delivered(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            planner = Mock(
                return_value={
                    "speak": True,
                    "tone": "warm playful",
                    "reason": "natural_moment",
                    "text": (
                        "Senhor, hoje parece "
                        "bem-disposto."
                    ),
                }
            )

            output = Mock()

            service = self._service(
                planner,
                output,
                tmp,
            )

            relational = Mock()
            relational.snapshot.return_value = {
                "rapport": "warm",
                "playful_momentum": "active",
            }

            with patch(
                (
                    "jarvis_core.services."
                    "companion_presence."
                    "personal_cognition"
                ),
                return_value=self._cognition(),
            ), patch(
                (
                    "jarvis_core.services."
                    "companion_presence."
                    "relational_presence"
                ),
                return_value=relational,
            ):
                result = (
                    service.evaluate_once()
                )

            self.assertTrue(
                result["spoken"]
            )
            output.assert_called_once()

            status = service.status()

            self.assertTrue(
                status[
                    "relational_state_driven"
                ]
            )
            self.assertNotIn(
                "flirt_enabled",
                status,
            )
            self.assertNotIn(
                "flirt_intensity",
                status,
            )

    def test_planner_receives_relational_state(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            planner = Mock(
                return_value={
                    "speak": False,
                    "tone": "neutral",
                    "reason": "silence",
                    "text": "",
                }
            )

            service = self._service(
                planner,
                Mock(),
                tmp,
            )

            relational = Mock()
            relational.snapshot.return_value = {
                "rapport": "close",
                "relational_openness": "open",
                "sensual_tension": "suggestive",
            }

            with patch(
                (
                    "jarvis_core.services."
                    "companion_presence."
                    "personal_cognition"
                ),
                return_value=self._cognition(),
            ), patch(
                (
                    "jarvis_core.services."
                    "companion_presence."
                    "relational_presence"
                ),
                return_value=relational,
            ):
                service.evaluate_once()

            context = (
                planner.call_args.args[0]
            )

            self.assertEqual(
                context[
                    "relational_presence_state"
                ]["rapport"],
                "close",
            )
            self.assertNotIn(
                "flirt_enabled",
                context,
            )
            self.assertNotIn(
                "flirt_intensity",
                context,
            )

    def test_afternoon_blocks_false_current_night_claim(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            fixed_now = (
                datetime.now()
                .astimezone()
                .replace(
                    hour=15,
                    minute=40,
                    second=0,
                    microsecond=0,
                )
            )

            planner = Mock(
                return_value={
                    "speak": True,
                    "tone": "warm",
                    "reason": "recent",
                    "text": (
                        "Senhor, parece que est\u00e1 "
                        "a trabalhar \u00e0 noite. "
                        "Que tal um caf\u00e9?"
                    ),
                }
            )

            output = Mock()

            service = self._service(
                planner,
                output,
                tmp,
            )

            relational = Mock()
            relational.snapshot.return_value = {}

            with patch(
                (
                    "jarvis_core.services."
                    "companion_presence._now"
                ),
                return_value=fixed_now,
            ), patch(
                (
                    "jarvis_core.services."
                    "companion_presence."
                    "personal_cognition"
                ),
                return_value=self._cognition(
                    fixed_now
                ),
            ), patch(
                (
                    "jarvis_core.services."
                    "companion_presence."
                    "relational_presence"
                ),
                return_value=relational,
            ):
                result = (
                    service.evaluate_once()
                )

            self.assertTrue(
                result["eligible"]
            )
            self.assertFalse(
                result["spoken"]
            )
            self.assertEqual(
                result["reason"],
                "temporal_claim_conflict",
            )
            self.assertEqual(
                planner.call_args.args[0][
                    "day_period"
                ],
                "afternoon",
            )
            output.assert_not_called()


if __name__ == "__main__":
    unittest.main()
