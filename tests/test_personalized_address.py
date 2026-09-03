import json
import unittest
from pathlib import Path

class PersonalizedAddressTests(unittest.TestCase):
    def test_profile(self):
        p=json.loads(Path('defaults/user_profile.json').read_text(encoding='utf-8'))
        self.assertEqual(p['name'],'Tiago')
        self.assertEqual(p['address_as'],'Senhor')
        self.assertEqual(p['home']['locality'],'Furadouro')
    def test_prompt(self):
        c=Path('jarvis_core/cli.py').read_text(encoding='utf-8')
        self.assertIn('def current_address() -> str:',c)
        self.assertIn('text = input(f"{current_address()} > ").strip()',c)
if __name__=='__main__': unittest.main()
