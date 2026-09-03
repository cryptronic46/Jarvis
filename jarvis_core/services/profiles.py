from __future__ import annotations
from pathlib import Path
from typing import Any
import json, shutil

class ProfileManager:
    def __init__(self,path='memory/profiles.json',default_path='defaults/profiles.json'):
        self.path=Path(path); self.default_path=Path(default_path); self.path.parent.mkdir(parents=True,exist_ok=True); self._ensure()
    def _ensure(self):
        if self.path.exists(): return
        if self.default_path.exists(): shutil.copyfile(self.default_path,self.path)
        else: self.path.write_text('{"active_profile":"owner","profiles":{}}',encoding='utf-8')
    def _load(self)->dict[str,Any]:
        self._ensure()
        try:
            d=json.loads(self.path.read_text(encoding='utf-8')); return d if isinstance(d,dict) else {'active_profile':'owner','profiles':{}}
        except Exception: return {'active_profile':'owner','profiles':{}}
    def _save(self,d): self.path.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    def active_id(self): return str(self._load().get('active_profile') or 'owner')
    def active(self):
        d=self._load(); pid=self.active_id(); p=dict((d.get('profiles') or {}).get(pid) or {}); p['id']=pid; return p
    def status(self):
        d=self._load(); return {'ok':True,'active_profile':self.active(),'profiles':[{'id':pid,'display_name':p.get('display_name'),'address_as':p.get('address_as'),'role':p.get('role'),'voice_profile':p.get('voice_profile'),'active':pid==d.get('active_profile')} for pid,p in (d.get('profiles') or {}).items()],'permission_enforcement':True,'voice_binding_enforcement':False}
    def activate(self,profile_id):
        d=self._load(); pid=str(profile_id).strip().lower()
        if pid not in (d.get('profiles') or {}): return {'ok':False,'error':'UNKNOWN_PROFILE','profile':pid}
        d['active_profile']=pid; self._save(d); return {'ok':True,'active_profile':self.active(),'warning':'Troca manual para testes; Voice ID multiutilizador ainda não está em enforcement.'}
    def tool_allowed(self,tool_name):
        allowed=[str(x) for x in self.active().get('allowed_tools',[])]; return '*' in allowed or str(tool_name) in allowed
    def routine_allowed(self,name):
        allowed=[str(x).lower() for x in self.active().get('allowed_routines',[])]; return '*' in allowed or str(name).lower() in allowed
    def permissions(self,profile_id=None):
        d=self._load(); pid=str(profile_id or self.active_id()).lower(); p=(d.get('profiles') or {}).get(pid)
        if not p: return {'ok':False,'error':'UNKNOWN_PROFILE','profile':pid}
        return {'ok':True,'profile':pid,'role':p.get('role'),'allowed_tools':p.get('allowed_tools',[]),'allowed_routines':p.get('allowed_routines',[])}
_MANAGER=None
def manager():
    global _MANAGER
    if _MANAGER is None: _MANAGER=ProfileManager()
    return _MANAGER
def get_active_profile(): return manager().status()
def get_profile_permissions(profile_id=''): return manager().permissions(profile_id or None)
