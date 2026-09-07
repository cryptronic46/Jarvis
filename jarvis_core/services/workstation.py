import ctypes, platform

def lock_workstation():
    if platform.system().lower()!='windows': return {'ok':False,'error':'WINDOWS_ONLY'}
    try:
        ok=bool(ctypes.windll.user32.LockWorkStation()); return {'ok':ok,'locked':ok}
    except Exception as exc: return {'ok':False,'error':type(exc).__name__,'message':str(exc)}
