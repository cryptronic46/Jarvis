import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from jarvis_core.core.local_llm import NativeLlamaClient


class LocalLlmKeepAliveSemanticsTests(unittest.TestCase):
    def _client(self):
        settings = SimpleNamespace(
            native_llama_request_timeout_seconds=10,
        )
        client = NativeLlamaClient(settings)

        runtime = Mock()
        runtime.base_url = "http://127.0.0.1:11435"
        client.runtime = runtime

        client._json = Mock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "completion_tokens": 1,
                },
            }
        )

        return client, runtime

    def test_chat_keep_alive_false_does_not_release_runtime(self):
        client, runtime = self._client()

        result = client.chat(
            model="qwen3:8b",
            messages=[
                {
                    "role": "user",
                    "content": "hello",
                }
            ],
            keep_alive=False,
        )

        self.assertEqual(result.message.content, "ok")
        runtime.ensure_started.assert_called_once_with()
        runtime.shutdown.assert_not_called()

    def test_generate_keep_alive_false_does_not_release_runtime(self):
        client, runtime = self._client()

        result = client.generate(
            model="qwen3:8b",
            prompt="hello",
            keep_alive=False,
        )

        self.assertEqual(result, {"ok": True})
        runtime.shutdown.assert_not_called()

    def test_chat_explicit_zero_forms_still_release_runtime(self):
        for value in (0, "0", "0s", "0.0"):
            with self.subTest(keep_alive=value):
                client, runtime = self._client()

                client.chat(
                    model="qwen3:8b",
                    messages=[
                        {
                            "role": "user",
                            "content": "hello",
                        }
                    ],
                    keep_alive=value,
                )

                runtime.shutdown.assert_called_once_with(
                    reason="keep_alive_zero"
                )

    def test_generate_explicit_zero_forms_still_release_runtime(self):
        for value in (0, "0", "0s", "0.0"):
            with self.subTest(keep_alive=value):
                client, runtime = self._client()

                client.generate(
                    model="qwen3:8b",
                    prompt="hello",
                    keep_alive=value,
                )

                runtime.shutdown.assert_called_once_with(
                    reason="release_model"
                )


if __name__ == "__main__":
    unittest.main()
