import tempfile
import time
import unittest
from pathlib import Path

from jarvis_core.core.events import EventBus
from jarvis_core.services.activity_trace import ActivityTraceService


class ActivityTrace0239Tests(unittest.TestCase):
    def test_safe_trace_exposes_observable_state_not_chain_of_thought(self):
        with tempfile.TemporaryDirectory() as td:
            events = EventBus(log_dir=str(Path(td) / "logs"))
            trace = ActivityTraceService(events, path=str(Path(td) / "trace.json"))
            trace.start()
            events.emit("VOICE_HEARD", text="abre o Brave", raw_text="avie o Brave", source="wake")
            events.emit("HYBRID_ROUTE", route="local", reason="normal_reasoning")
            events.emit("TOOL_EXECUTING", tool="open_app", arguments={"name": "Brave"})
            time.sleep(0.15)
            status = trace.status()
            trace.stop()
            joined = " ".join(x["detail"] for x in status["recent"])
            self.assertIn("avie o Brave", joined)
            self.assertIn("open_app", joined)
            self.assertIn("não expõe chain-of-thought", status["note"])

    def test_cli_has_activity_and_silence_controls(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        for marker in ["/activity on", "/activity status", "/silence status", "silence_latch.latch"]:
            self.assertIn(marker, text)
