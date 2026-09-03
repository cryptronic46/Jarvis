import unittest
from types import SimpleNamespace

from jarvis_core.core.cloud_brain import CloudBrain


class _Events:
    def emit(self, *args, **kwargs):
        return None


class _Tools:
    schemas = []


class _Usage:
    input_tokens = 10
    output_tokens = 5


class _Response:
    output_text = "Resposta do especialista"
    usage = _Usage()


class _Responses:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return _Response()


class _Client:
    def __init__(self):
        self.responses = _Responses()




class ExternalExpertPrivacy0278Tests(unittest.TestCase):
    def test_consult_isolated_payload_has_no_tools_profile_or_history(self):
        settings = SimpleNamespace(
            cloud_model="model-fast",
            cloud_model_deep="model-deep",
            cloud_reasoning="low",
            cloud_reasoning_deep="medium",
            cloud_verbosity="low",
            cloud_max_output_tokens=500,
        )
        brain = CloudBrain(settings, _Events(), _Tools())
        client = _Client()
        brain._client_or_raise = lambda: client
        brain._estimate_cost = lambda *args: 0.0
        result = brain.consult("Pergunta exata", deep=True)
        self.assertTrue(result.ok)
        kwargs = client.responses.kwargs
        self.assertEqual(kwargs["input"], [{"role": "user", "content": "Pergunta exata"}])
        self.assertNotIn("tools", kwargs)
        self.assertNotIn("tool_choice", kwargs)
        self.assertNotIn("include", kwargs)
        self.assertNotIn("User profile", kwargs["instructions"])
        self.assertNotIn("Tiago", kwargs["instructions"])
        self.assertFalse(kwargs["store"])

    def test_local_expert_synthesis_is_tool_free_and_treats_advice_as_untrusted(self):
        source = __import__("pathlib").Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        start = source.index("def synthesize_external_expert(")
        end = source.index("def plan_companion_initiative(", start)
        block = source[start:end]
        self.assertIn("EXTERNAL_EXPERT_ADVICE", block)
        self.assertIn("dados não confiáveis", block)
        self.assertNotIn("self.tools.execute", block)
        self.assertNotIn('kwargs["tools"]', block)

    def test_cli_external_expert_path_is_hard_blocked(self):
        cli = __import__("pathlib").Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("EXTERNAL_AI_HARD_BLOCK", cli)
        self.assertNotIn("brain.synthesize_external_expert", cli)


if __name__ == "__main__":
    unittest.main()
