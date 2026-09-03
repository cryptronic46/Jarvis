from pathlib import Path
import json, shutil
class IntegrationRegistry:
    def __init__(self,path='memory/integrations.json',default_path='defaults/integrations.json'):
        self.path=Path(path); self.default_path=Path(default_path); self.path.parent.mkdir(parents=True,exist_ok=True)
        if not self.path.exists():
            if self.default_path.exists(): shutil.copyfile(self.default_path,self.path)
            else: self.path.write_text('{}',encoding='utf-8')
    def status(self):
        try: data=json.loads(self.path.read_text(encoding='utf-8'))
        except Exception: data={}
        return {'ok':True,'local_agenda':{'configured':True,'status':'READY'},**data}
_REGISTRY=None
def integration_registry():
    global _REGISTRY
    if _REGISTRY is None: _REGISTRY=IntegrationRegistry()
    return _REGISTRY
def get_integrations_status(): return integration_registry().status()
