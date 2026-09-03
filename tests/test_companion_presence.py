import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jarvis_core.services.companion_presence import CompanionPresenceService


class CompanionPresenceTests(unittest.TestCase):
    def _service(self, planner, output, root):
        return CompanionPresenceService(
            planner,
            output,
            state_path=Path(root) / "companion.json",
            enabled=True,
            flirt_enabled=True,
            flirt_intensity=0.6,
            check_interval_seconds=60,
            startup_delay_seconds=0,
            decision_cooldown_seconds=30,
            min_interval_minutes=2,
            idle_seconds=30,
            quiet_start_hour=0,
            quiet_end_hour=0,
            max_per_hour=2,
        )

    def test_model_can_choose_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = Mock(return_value={
                "speak": False,
                "tone": "neutral",
                "reason": "nothing_natural_to_add",
                "text": "",
            })
            output = Mock()
            service = self._service(planner, output, tmp)
            recent = (datetime.now().astimezone() - timedelta(minutes=3)).isoformat()
            cognition = Mock()
            cognition.state.return_value = {"last_interaction_at": recent}
            with patch("jarvis_core.services.companion_presence.personal_cognition", return_value=cognition):
                result = service.evaluate_once()
            self.assertTrue(result["eligible"])
            self.assertFalse(result["spoken"])
            planner.assert_called_once()
            output.assert_not_called()

    def test_model_generated_message_is_delivered(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = Mock(return_value={
                "speak": True,
                "tone": "flirty",
                "reason": "relaxed_context",
                "text": "Senhor, hoje está perigosamente difícil ignorá-lo.",
            })
            output = Mock()
            service = self._service(planner, output, tmp)
            recent = (datetime.now().astimezone() - timedelta(minutes=3)).isoformat()
            cognition = Mock()
            cognition.state.return_value = {"last_interaction_at": recent}
            with patch("jarvis_core.services.companion_presence.personal_cognition", return_value=cognition):
                result = service.evaluate_once()
            self.assertTrue(result["spoken"])
            output.assert_called_once()
            status = service.status()
            self.assertTrue(status["initiative_model_driven"])
            self.assertFalse(status["prewritten_flirt_lines"])
            self.assertFalse(status["subjective_volition_claimed"])

    def test_intensity_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(Mock(), Mock(), tmp)
            self.assertFalse(service.set_intensity(1.5)["ok"])
            self.assertTrue(service.set_intensity(0.75)["ok"])
            self.assertEqual(service.status()["flirt_intensity"], 0.75)


if __name__ == "__main__":
    unittest.main()
