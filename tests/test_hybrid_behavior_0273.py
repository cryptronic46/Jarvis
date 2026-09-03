import unittest
from jarvis_core.core.config import Settings
from jarvis_core.core.hybrid_brain import HybridBrain

class Events:
    def __init__(self): self.rows=[]
    def emit(self,*args,**kwargs): self.rows.append((args,kwargs))

class Local:
    def __init__(self, answer='LOCAL_OK', fail=False): self.calls=[]; self.answer=answer; self.fail=fail
    def ask(self,text):
        self.calls.append(text)
        if self.fail: raise RuntimeError('local fail')
        return self.answer
    def clear_history(self): pass

class CloudAnswer:
    text='CLOUD_OK'; model='external-test'; elapsed_ms=12; estimated_usd=0.0

class Cloud:
    def __init__(self): self.calls=[]
    def available(self): return True
    def ask(self,text,use_web=False,deep=False): self.calls.append((text,use_web,deep)); return CloudAnswer()
    def clear_history(self): pass

class HybridBehavior0273Tests(unittest.TestCase):
    def settings(self):
        s=Settings()
        s.external_ai_enabled=True
        s.cloud_enabled=True
        s.external_ai_complex_only=True
        s.external_ai_complexity_threshold=4
        s.external_ai_auto_escalate_complex=True
        s.cloud_fallback_on_local_error=False
        s.performance_cloud_offload_under_pressure=False
        return s

    def test_simple_request_never_calls_external_ai(self):
        local=Local(); cloud=Cloud()
        brain=HybridBrain(self.settings(),Events(),local,cloud_brain=cloud)
        result=brain.ask('Quanto é 2 mais 2?')
        self.assertEqual(result.route,'LOCAL')
        self.assertEqual(len(local.calls),1)
        self.assertEqual(cloud.calls,[])

    def test_simple_local_failure_does_not_call_external_ai(self):
        local=Local(fail=True); cloud=Cloud()
        brain=HybridBrain(self.settings(),Events(),local,cloud_brain=cloud)
        result=brain.ask('Diz olá')
        self.assertEqual(result.route,'LOCAL')
        self.assertEqual(cloud.calls,[])

    def test_complex_request_stays_local_when_local_answer_is_sufficient(self):
        order=[]
        class OrderedLocal(Local):
            def ask(self,text): order.append('local'); return super().ask(text)
        class OrderedCloud(Cloud):
            def ask(self,text,use_web=False,deep=False): order.append('cloud'); return super().ask(text,use_web,deep)
        local=OrderedLocal(); cloud=OrderedCloud()
        brain=HybridBrain(self.settings(),Events(),local,cloud_brain=cloud)
        text=('Faz uma auditoria completa desta arquitetura complexa, analisa profundamente os trade-offs, '
              'refatora tudo e apresenta um plano detalhado multi-etapa com alternativas. ')*6
        result=brain.ask(text)
        self.assertEqual(order,['local'])
        self.assertEqual(result.route,'LOCAL')
        self.assertEqual(result.text,'LOCAL_OK')

    def test_complex_local_failure_never_escalates_external_ai(self):
        order=[]
        class FailingLocal(Local):
            def ask(self,text):
                order.append('local')
                return super().ask(text)
        class OrderedCloud(Cloud):
            def ask(self,text,use_web=False,deep=False):
                order.append('cloud')
                return super().ask(text,use_web,deep)
        local=FailingLocal(fail=True); cloud=OrderedCloud()
        brain=HybridBrain(self.settings(),Events(),local,cloud_brain=cloud)
        text=('Faz uma auditoria completa desta arquitetura complexa, analisa profundamente os trade-offs, '
              'refatora tudo e apresenta um plano detalhado multi-etapa com alternativas. ')*6
        result=brain.ask(text)
        self.assertEqual(order,['local'])
        self.assertEqual(result.route,'LOCAL')
        self.assertEqual(result.reason,'local_first')

if __name__=='__main__': unittest.main()
