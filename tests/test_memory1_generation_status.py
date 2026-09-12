from __future__ import annotations

from threading import RLock
import unittest

from jarvis_core.core.brain import JarvisBrain
from jarvis_core.core.config import Settings
from jarvis_core.core.generation_result import (
    BrainAnswer,
    GenerationStatus,
)
from jarvis_core.core.hybrid_brain import HybridBrain
from jarvis_core.core.local_llm import LocalLLMError


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, *args, **kwargs):
        self.rows.append((args, kwargs))


class _ProbeBrain(JarvisBrain):
    def __init__(self, outcome):
        self._lock = RLock()
        self._outcome = outcome

    def _ask_locked(
        self,
        user_text,
        *,
        request=None,
        memory_grounding_context="",
    ):
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class _Local:
    def __init__(self, outcome):
        self.outcome = outcome

    def ask(self, text, **kwargs):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class Memory1GenerationStatusTests(unittest.TestCase):
    def settings(self):
        settings = Settings()
        settings.external_ai_enabled = False
        settings.cloud_enabled = False
        settings.epistemic_learning_enabled = False
        settings.autonomy_proactive_learning_enabled = False
        settings.external_ai_complexity_threshold = 4
        return settings

    def test_brain_answer_contract_is_typed(self):
        result = BrainAnswer(
            text="ok",
            generation_status=GenerationStatus.SUCCESS,
        )
        self.assertEqual(result.text, "ok")
        self.assertIs(result.generation_status, GenerationStatus.SUCCESS)

    def test_jarvis_brain_originates_success_status(self):
        brain = _ProbeBrain("resposta")
        result = brain.ask("olá")
        self.assertEqual(result.text, "resposta")
        self.assertIs(result.generation_status, GenerationStatus.SUCCESS)

    def test_jarvis_brain_maps_local_llm_error_to_model_failure(self):
        brain = _ProbeBrain(LocalLLMError("down"))
        result = brain.ask("olá")
        self.assertEqual(result.text, "")
        self.assertIs(
            result.generation_status,
            GenerationStatus.MODEL_FAILURE,
        )

    def test_jarvis_brain_does_not_mask_programming_bug(self):
        brain = _ProbeBrain(TypeError("bug"))
        with self.assertRaises(TypeError):
            brain.ask("olá")

    def test_hybrid_propagates_typed_model_failure(self):
        local = _Local(
            BrainAnswer(
                text="",
                generation_status=GenerationStatus.MODEL_FAILURE,
            )
        )
        hybrid = HybridBrain(self.settings(), _Events(), local)
        result = hybrid.ask("Diz olá")
        self.assertIs(
            result.generation_status,
            GenerationStatus.MODEL_FAILURE,
        )
        self.assertEqual(result.route, "LOCAL")

    def test_hybrid_maps_local_llm_exception_to_model_failure(self):
        hybrid = HybridBrain(
            self.settings(),
            _Events(),
            _Local(LocalLLMError("down")),
        )
        result = hybrid.ask("Diz olá")
        self.assertIs(
            result.generation_status,
            GenerationStatus.MODEL_FAILURE,
        )

    def test_hybrid_does_not_mask_programming_bug(self):
        hybrid = HybridBrain(
            self.settings(),
            _Events(),
            _Local(RuntimeError("bug")),
        )
        with self.assertRaises(RuntimeError):
            hybrid.ask("Diz olá")


if __name__ == "__main__":
    unittest.main()
