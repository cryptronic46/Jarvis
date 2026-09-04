import unittest

from jarvis_core.services.language_refinement import (
    refine_assistant_text,
    refinement_status,
)
from jarvis_core.services.request_intent import (
    sanitize_assistant_text,
    python_code_blocks_valid,
    python_code_response_needs_repair,
)
from jarvis_core.services.speech_text import prepare_for_speech


class LanguageRefinementHotfixTests(unittest.TestCase):
    def test_ptpt_contraction_fixes_observed_self_state_phrase(self):
        text = "Neste momento, a minha intenção ativa está focada em a nossa conversa atual."
        self.assertEqual(
            refine_assistant_text(text),
            "Neste momento, a minha intenção ativa está focada na nossa conversa atual.",
        )

    def test_written_output_uses_same_refiner(self):
        text = "Minha função usa a tela e posso compartilhar registros com você."
        out = sanitize_assistant_text(text)
        self.assertIn("A minha função", out)
        self.assertIn("ecrã", out)
        self.assertIn("posso partilhar registos consigo", out)
        self.assertFalse(out.startswith("Minha função"))
        for bad in ("tela", "compartilhar", "registros", "você"):
            self.assertNotIn(bad.lower(), out.lower())

    def test_speech_uses_same_ptpt_refinement(self):
        out = prepare_for_speech(
            "Estou focada em a nossa conversa e posso compartilhar um registro com você."
        )
        self.assertIn("focada na nossa conversa", out)
        self.assertIn("posso partilhar um registo consigo", out)

    def test_machine_readable_json_is_not_rewritten(self):
        raw = '{"text":"Minha função usa a tela","locale":"pt-BR"}'
        self.assertEqual(refine_assistant_text(raw), raw)

    def test_html_entities_and_escaped_markdown_are_repaired_only_in_prose(self):
        raw = r"Definição da função&#x20;****`contar_linhas` e \*\*resultado\*\*.\n```python\ntexto = '&#x20;****'\n```"
        out = refine_assistant_text(raw)
        self.assertIn("Definição da função **`contar_linhas`", out)
        self.assertIn("**resultado**", out)
        self.assertIn("texto = '&#x20;****'", out)

    def test_observed_brazilian_terms_are_localized(self):
        out = refine_assistant_text("O gerenciador retorna arquivos. Estou tudo funcionando corretamente.")
        self.assertEqual(out, "O gestor devolve ficheiros. Está tudo a funcionar corretamente.")
    def test_code_is_preserved_verbatim(self):
        raw = "Use `registro = usuario` e depois explico: o usuário vê a tela."
        out = refine_assistant_text(raw)
        self.assertIn("`registro = usuario`", out)
        self.assertIn("o utilizador vê o ecrã", out)

    def test_sanitizer_preserves_python_block_indentation(self):
        raw = "```python\ndef add_task(task):\n    with open('tasks.txt') as file:\n        file.write(task)\n```"
        self.assertEqual(sanitize_assistant_text(raw), raw)

    def test_python_validator_rejects_broken_indentation_and_syntax(self):
        broken = "```python\ndef soma(a, b):\nresultado = a + b\nreturn resultado\n```"
        self.assertFalse(python_code_blocks_valid(broken))
        self.assertTrue(python_code_response_needs_repair("Mostra código Python completo.", broken))
        valid = "```python\ndef soma(a, b):\n    resultado = a + b\n    return resultado\n```"
        self.assertTrue(python_code_blocks_valid(valid))
        self.assertFalse(python_code_response_needs_repair("Mostra código Python completo.", valid))

    def test_python_validator_rejects_malformed_try_except(self):
        broken = "```python\ntry:\n    print(1 / 0)\nexcept except ZeroDivisionError:\n    print('erro')\n```"
        self.assertFalse(python_code_blocks_valid(broken))
    def test_duplicate_sentence_is_removed(self):
        out = refine_assistant_text(
            "A confiança não é veracidade. A confiança não é veracidade."
        )
        self.assertEqual(out.count("A confiança não é veracidade."), 1)

    def test_brain_requires_valid_unescaped_indented_python(self):
        from pathlib import Path
        prompt = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("four literal spaces", prompt)
        self.assertIn("unescaped ```python fenced block", prompt)
        self.assertIn("never escape underscores", prompt)

    def test_refiner_is_local_and_applies_to_written_and_speech(self):
        status = refinement_status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["locale"], "pt-PT")
        self.assertFalse(status["external_ai"])
        self.assertIn("written_response", status["applies_to"])
        self.assertIn("speech_input", status["applies_to"])


if __name__ == "__main__":
    unittest.main()
