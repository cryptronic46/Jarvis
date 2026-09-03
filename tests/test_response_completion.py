import unittest
from types import SimpleNamespace

from jarvis_core.services.response_completion import (
    merge_continuation,
    response_done_reason,
    response_was_truncated,
)


class ResponseCompletionTests(unittest.TestCase):
    def test_explicit_length_reason_is_truncated(self):
        response = SimpleNamespace(done_reason="length", eval_count=160)
        self.assertTrue(
            response_was_truncated(
                response,
                requested_predict=160,
                content="Não execute ficheiros ou",
            )
        )

    def test_stop_reason_is_not_truncated(self):
        response = SimpleNamespace(done_reason="stop", eval_count=87)
        self.assertFalse(
            response_was_truncated(
                response,
                requested_predict=160,
                content="Resposta concluída.",
            )
        )

    def test_explicit_stop_wins_even_at_budget(self):
        response = SimpleNamespace(done_reason="stop", eval_count=160)
        self.assertFalse(
            response_was_truncated(
                response,
                requested_predict=160,
                content="Resposta termina sem pontuação",
            )
        )

    def test_legacy_eval_count_detects_mid_sentence_limit(self):
        response = {"eval_count": 160}
        self.assertTrue(
            response_was_truncated(
                response,
                requested_predict=160,
                content="Não execute ficheiros ou",
            )
        )

    def test_legacy_eval_count_does_not_continue_complete_sentence(self):
        response = {"eval_count": 160}
        self.assertFalse(
            response_was_truncated(
                response,
                requested_predict=160,
                content="Resposta concluída.",
            )
        )

    def test_merge_removes_repeated_overlap(self):
        merged = merge_continuation(
            "Não execute ficheiros ou programas desconhecidos",
            "programas desconhecidos sem os verificar primeiro.",
        )
        self.assertEqual(
            merged,
            "Não execute ficheiros ou programas desconhecidos sem os verificar primeiro.",
        )

    def test_done_reason_supports_dict(self):
        self.assertEqual(
            response_done_reason({"done_reason": "length"}),
            "length",
        )


if __name__ == "__main__":
    unittest.main()
