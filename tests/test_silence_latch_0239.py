import tempfile
import unittest
from pathlib import Path

from jarvis_core.core.events import EventBus
from jarvis_core.services.silence_latch import SilenceLatchService


class SilenceLatch0239Tests(unittest.TestCase):
    def test_latch_invalidates_inflight_generation_until_fresh_request(self):
        with tempfile.TemporaryDirectory() as td:
            events = EventBus(log_dir=td)
            latch = SilenceLatchService(events)
            generation = latch.generation()
            self.assertTrue(latch.output_allowed(generation))
            latch.latch(source="barge_in")
            self.assertFalse(latch.output_allowed(generation))
            self.assertTrue(latch.active())
            latch.release(source="verified_wake")
            self.assertFalse(latch.output_allowed(generation))
            fresh = latch.generation()
            self.assertTrue(latch.output_allowed(fresh))

    def test_status_counts_suppressed_output(self):
        with tempfile.TemporaryDirectory() as td:
            latch = SilenceLatchService(EventBus(log_dir=td))
            latch.latch()
            latch.mark_suppressed_response("response")
            latch.mark_suppressed_response("proactive")
            status = latch.status()
            self.assertEqual(status["suppressed_responses"], 1)
            self.assertEqual(status["suppressed_proactive"], 1)
