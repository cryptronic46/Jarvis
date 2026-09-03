from pathlib import Path
import ctypes, json, platform
class PrivacyState:
    def __init__(self,path='memory/privacy_state.json'):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        if not self.path.exists(): self._save({'enabled':False})
    def _load(self):
        try:
            d=json.loads(self.path.read_text(encoding='utf-8')); return d if isinstance(d,dict) else {'enabled':False}
        except Exception: return {'enabled':False}
    def _save(self,d): self.path.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    @property
    def enabled(self): return bool(self._load().get('enabled'))
    def set(self,enabled): self._save({'enabled':bool(enabled)}); return {'ok':True,'privacy_mode':bool(enabled),'cloud_allowed':not bool(enabled),'external_network_research_allowed':not bool(enabled)}
    def status(self): return {'ok':True,'privacy_mode':self.enabled,'cloud_allowed':not self.enabled,'external_network_research_allowed':not self.enabled}
_STATE=None
def privacy_state():
    global _STATE
    if _STATE is None: _STATE=PrivacyState()
    return _STATE
def set_privacy_mode(enabled): return privacy_state().set(enabled)
def get_privacy_status(): return privacy_state().status()
def lock_workstation():
    if platform.system().lower()!='windows': return {'ok':False,'error':'WINDOWS_ONLY'}
    try:
        ok=bool(ctypes.windll.user32.LockWorkStation()); return {'ok':ok,'locked':ok}
    except Exception as exc: return {'ok':False,'error':type(exc).__name__,'message':str(exc)}
