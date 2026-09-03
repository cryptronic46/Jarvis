import unittest
from jarvis_core.core.freshness import requires_current_gpu, requires_current_system

class FreshnessTests(unittest.TestCase):
    def test_current_gpu(self):
        self.assertTrue(requires_current_gpu("Qual é a temperatura atual da RTX 5070?"))

    def test_old_gpu_question_does_not_force(self):
        self.assertFalse(requires_current_gpu("Qual era a temperatura da GPU?"))

    def test_current_pc(self):
        self.assertTrue(requires_current_system("Como está o meu PC agora?"))

if __name__ == "__main__":
    unittest.main()
