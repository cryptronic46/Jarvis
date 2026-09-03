import time
import unittest

from jarvis_core.services.listening_watchdog import ListeningWatchdogService


class FakeEvents:
    def __init__(self):
        self.rows = []
    def emit(self, name, **data):
        self.rows.append((name, data))


class FakeSpeech:
    def __init__(self):
        self.speaking = False
    def status(self):
        return {"speaking": self.speaking}


class FakeWake:
    def __init__(self):
        self.state = {
            "enabled": True,
            "configured": True,
            "enrolled": True,
            "running": True,
            "stream_active": True,
            "hard_paused": False,
            "audio_suppressed": False,
            "last_error": None,
        }
        self.stop_calls = 0
        self.start_calls = 0
        self.unsuppress_calls = 0
    def status(self):
        return dict(self.state)
    def stop(self):
        self.stop_calls += 1
        self.state["running"] = False
        self.state["stream_active"] = False
    def start(self):
        self.start_calls += 1
        self.state["running"] = True
        self.state["stream_active"] = True
        return {"ok": True}
    def suppress_audio(self, enabled, *, reason="external", tail_seconds=None):
        if not enabled:
            self.unsuppress_calls += 1
        self.state["audio_suppressed"] = bool(enabled)


class ListeningWatchdogTests(unittest.TestCase):
    def build(self):
        events = FakeEvents(); wake = FakeWake(); speech = FakeSpeech()
        svc = ListeningWatchdogService(
            events, wake, speech, enabled=True, interval_seconds=1,
            stream_grace_seconds=3, recovery_cooldown_seconds=5,
        )
        return svc, events, wake, speech

    def test_manual_recovery_reopens_wake_stream(self):
        svc, events, wake, speech = self.build()
        wake.state["stream_active"] = False
        result = svc.recover("owner_manual")
        self.assertTrue(result["ok"])
        self.assertEqual(wake.stop_calls, 1)
        self.assertEqual(wake.start_calls, 1)
        self.assertTrue(wake.state["stream_active"])
        self.assertTrue(any(name == "LISTENING_RECOVERY" for name, _ in events.rows))

    def test_does_not_recover_while_tts_is_speaking(self):
        svc, events, wake, speech = self.build()
        speech.speaking = True
        wake.state["stream_active"] = False
        result = svc.recover("owner_manual")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "TTS_ACTIVE")
        self.assertEqual(wake.stop_calls, 0)

    def test_stale_tts_suppression_is_cleared_when_idle(self):
        svc, events, wake, speech = self.build()
        wake.state["audio_suppressed"] = True
        svc._check_once()
        self.assertEqual(wake.unsuppress_calls, 1)
        self.assertFalse(wake.state["audio_suppressed"])
        self.assertEqual(wake.stop_calls, 0)

    def test_hard_pause_is_respected(self):
        svc, events, wake, speech = self.build()
        wake.state["hard_paused"] = True
        wake.state["stream_active"] = False
        svc._check_once()
        self.assertEqual(wake.stop_calls, 0)
        self.assertEqual(wake.start_calls, 0)

    def test_disarmed_watchdog_does_not_restart_owner_disabled_wake(self):
        svc, events, wake, speech = self.build()
        svc.set_armed(False)
        wake.state["running"] = False
        wake.state["stream_active"] = False
        svc._check_once()
        self.assertEqual(wake.start_calls, 0)
        self.assertFalse(svc.status()["armed"])

    def test_dead_stream_recovers_after_grace(self):
        svc, events, wake, speech = self.build()
        wake.state["stream_active"] = False
        svc._check_once()
        self.assertIsNotNone(svc._unhealthy_since)
        svc._unhealthy_since -= 10.0
        svc._last_recovery_at -= 10.0
        svc._check_once()
        self.assertEqual(wake.start_calls, 1)
        self.assertTrue(wake.state["stream_active"])


if __name__ == "__main__":
    unittest.main()
