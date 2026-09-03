import json
import tempfile
import unittest
from pathlib import Path
from jarvis_core.services.user_memory import UserMemoryStore

class UserMemoryTests(unittest.TestCase):
    def test_profile_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); default=root/'default.json'; default.write_text(json.dumps({'name':'Tiago','address_as':'Senhor','home':{'label':'Furadouro, Ovar'}}),encoding='utf-8')
            memory=root/'memory'; s=UserMemoryStore(memory,default)
            self.assertEqual(s.profile()['name'],'Tiago')
            profile=s.profile(); profile['name']='Tiago Persistente'; s.profile_path.write_text(json.dumps(profile),encoding='utf-8')
            default.write_text(json.dumps({'name':'Novo Default'}),encoding='utf-8')
            self.assertEqual(UserMemoryStore(memory,default).profile()['name'],'Tiago Persistente')

    def test_fact_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); default=root/'default.json'; default.write_text('{"name":"Tiago","address_as":"Senhor"}',encoding='utf-8')
            s=UserMemoryStore(root/'memory',default); self.assertTrue(s.remember('Prefiro café sem açúcar.','preference')['ok'])
            r=s.recall('café',10); self.assertEqual(len(r['facts']),1)

    def test_ordinary_relationship_fact_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); default=root/'default.json'; default.write_text('{"name":"Tiago","address_as":"Senhor"}',encoding='utf-8')
            s=UserMemoryStore(root/'memory',default)
            result=s.remember('O nome da minha mulher é ISA.','relationship')
            self.assertTrue(result['ok'])
            self.assertEqual(s.recall('mulher',10)['facts'][0]['fact'],'O nome da minha mulher é ISA.')

    def test_credential_secrets_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); default=root/'default.json'; default.write_text('{"name":"Tiago","address_as":"Senhor"}',encoding='utf-8')
            s=UserMemoryStore(root/'memory',default)
            for secret in (
                'A minha API key é sk-test-secret',
                'A minha password é supersecreta',
                'O meu PIN é 1234',
                'A minha seed phrase é alpha beta gamma delta',
            ):
                result=s.remember(secret,'user_explicit')
                self.assertFalse(result['ok'], secret)
                self.assertEqual(result['error'],'SECRET_MEMORY_BLOCKED')
            self.assertEqual(s.facts(),[])

    def test_credential_concept_without_secret_value_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); default=root/'default.json'; default.write_text('{"name":"Tiago","address_as":"Senhor"}',encoding='utf-8')
            s=UserMemoryStore(root/'memory',default)
            result=s.remember('Prefiro guardar API keys no Windows Credential Manager.','preference')
            self.assertTrue(result['ok'])

if __name__=='__main__': unittest.main()
