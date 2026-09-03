from __future__ import annotations
from pathlib import Path
from datetime import datetime, timedelta
from secrets import token_hex
import json
class AgendaStore:
    def __init__(self,path='memory/agenda.json'):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        if not self.path.exists(): self._save({'items':[]})
    def _load(self):
        try:
            d=json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(d,dict): d.setdefault('items',[]); return d
        except Exception: pass
        return {'items':[]}
    def _save(self,d): self.path.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    @staticmethod
    def _parse_when(value):
        if not value: return None
        text=str(value).strip()
        for c in (text,text.replace(' ','T',1)):
            try:
                dt=datetime.fromisoformat(c)
                if dt.tzinfo is None: dt=dt.astimezone()
                return dt.isoformat(timespec='minutes')
            except ValueError: pass
        raise ValueError('Formato inválido. Usa YYYY-MM-DD HH:MM.')
    def add(self,title,when=None,kind='task',notes=''):
        title=str(title).strip()
        if not title: return {'ok':False,'error':'EMPTY_TITLE'}
        kind=str(kind or 'task').lower(); kind=kind if kind in {'task','event','reminder'} else 'task'
        try: when_iso=self._parse_when(when)
        except ValueError as e: return {'ok':False,'error':'INVALID_DATETIME','message':str(e)}
        d=self._load(); item={'id':token_hex(3).upper(),'title':title[:300],'kind':kind,'when':when_iso,'notes':str(notes)[:1000],'done':False,'notified':False,'created_at':datetime.now().astimezone().isoformat(timespec='seconds')}; d['items'].append(item); self._save(d); return {'ok':True,'item':item}
    def list_items(self,window='upcoming',include_done=False,limit=30):
        now=datetime.now().astimezone(); today=now.date(); tomorrow=today+timedelta(days=1); rows=[]
        for item in self._load().get('items',[]):
            if not include_done and item.get('done'): continue
            dt=None
            if item.get('when'):
                try: dt=datetime.fromisoformat(item['when'])
                except ValueError: pass
            win=str(window or 'upcoming').lower(); keep=True
            if win=='today': keep=bool(dt and dt.astimezone().date()==today)
            elif win=='tomorrow': keep=bool(dt and dt.astimezone().date()==tomorrow)
            elif win=='upcoming': keep=dt is None or dt>=now-timedelta(minutes=1)
            if keep: rows.append(item)
        rows.sort(key=lambda x:(x.get('when') is None,x.get('when') or '9999',x.get('created_at') or ''))
        return {'ok':True,'window':window,'items':rows[:max(1,min(int(limit),100))]}
    def complete(self,item_id):
        d=self._load(); wanted=str(item_id).strip().upper()
        for item in d.get('items',[]):
            if str(item.get('id')).upper()==wanted:
                item['done']=True; item['completed_at']=datetime.now().astimezone().isoformat(timespec='seconds'); self._save(d); return {'ok':True,'item':item}
        return {'ok':False,'error':'AGENDA_ITEM_NOT_FOUND'}
    def due_reminders(self,grace_minutes=10):
        now=datetime.now().astimezone(); d=self._load(); due=[]; changed=False
        for item in d.get('items',[]):
            if item.get('done') or item.get('notified') or not item.get('when'): continue
            try: dt=datetime.fromisoformat(item['when'])
            except ValueError: continue
            if dt<=now<=dt+timedelta(minutes=grace_minutes): item['notified']=True; due.append(dict(item)); changed=True
        if changed: self._save(d)
        return due
    def briefing(self):
        today=self.list_items('today',limit=20)['items']; pending=[x for x in self._load().get('items',[]) if not x.get('done')]
        return {'today_count':len(today),'pending_count':len(pending),'today':today[:5]}
_STORE=None
def agenda_store():
    global _STORE
    if _STORE is None: _STORE=AgendaStore()
    return _STORE
def add_agenda_item(title,when='',kind='task',notes=''): return agenda_store().add(title,when or None,kind,notes)
def list_agenda_items(window='upcoming',include_done=False,limit=30): return agenda_store().list_items(window,include_done,limit)
def complete_agenda_item(item_id): return agenda_store().complete(item_id)
