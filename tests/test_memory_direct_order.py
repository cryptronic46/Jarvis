import unittest

from jarvis_core.core.fast_router import _extract_explicit_memory_fact


class DirectMemoryOrderTests(unittest.TestCase):
    def test_memoriza_natural_fact_without_que(self):
        text = (
            "Jarvis, memoriza o nome da minha mulher: Ana Isa Guimarães Lopes, "
            "e a data de nascimento: 27 de Fevereiro de 1987."
        )
        fact = _extract_explicit_memory_fact(text)
        self.assertIsNotNone(fact)
        self.assertIn("Ana Isa Guimarães Lopes", fact)
        self.assertIn("27 de Fevereiro de 1987", fact)

    def test_quero_que_memorizes_natural_fact(self):
        fact = _extract_explicit_memory_fact(
            "Quero que memorizes o nome da minha mulher e a data de nascimento dela."
        )
        self.assertEqual(
            fact,
            "o nome da minha mulher e a data de nascimento dela",
        )

    def test_bare_memoriza_isso_is_not_stored_as_literal_fact(self):
        self.assertIsNone(_extract_explicit_memory_fact("Memoriza isso."))


if __name__ == "__main__":
    unittest.main()
