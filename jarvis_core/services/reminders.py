from threading import Event, Thread
from jarvis_core.services.agenda import agenda_store
class ReminderService:
    def __init__(self,events,callback=None,interval_seconds=20.0): self.events=events; self.callback=callback; self.interval_seconds=max(5.0,float(interval_seconds)); self._stop=Event(); self._thread=None
    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear(); self._thread=Thread(target=self._loop,name='jarvis-reminders',daemon=True); self._thread.start()
    def stop(self): self._stop.set()
    def _loop(self):
        while not self._stop.wait(self.interval_seconds):
            try:
                for item in agenda_store().due_reminders():
                    text=f"Lembrete: {item.get('title')}."; self.events.emit('REMINDER_DUE',item_id=item.get('id'),title=item.get('title'))
                    if self.callback: self.callback(text)
            except Exception as exc: self.events.emit('REMINDER_ERROR',error=f'{type(exc).__name__}: {exc}')
