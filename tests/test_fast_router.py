import json
import unittest

from jarvis_core.core.fast_router import FastCommandRouter


class FakeEvents:
    def __init__(self):
        self.events = []

    def emit(self, name, **data):
        self.events.append((name, data))


class FakeApps:
    def list_apps(self):
        return [
            {"id": "brave", "name": "Brave", "aliases": ["browser"]},
            {"id": "spotify", "name": "Spotify", "aliases": []},
        ]


class FakeTools:
    def __init__(self):
        self.request_started_at = None
        self.calls = []

    def execute(self, name, args=None):
        args = args or {}
        self.calls.append((name, args))

        if name == "open_application":
            return json.dumps({"ok": True})
        if name == "close_application":
            return json.dumps({
                "confirmation_required": True,
                "token": "ABC123",
                "tool": name,
            })
        if name == "set_master_volume":
            return json.dumps({
                "ok": True,
                "volume_percent": args["percent"],
            })
        if name == "set_mute":
            return json.dumps({"ok": True, "muted": args["muted"]})
        if name == "get_pre_request_telemetry":
            return json.dumps({
                "cpu_percent": 12.0,
                "memory_percent": 41.0,
                "gpu": [{
                    "temperature_c": 42,
                    "utilization_percent": 10,
                    "memory_used_mib": 2048,
                    "memory_total_mib": 12288,
                }],
            })
        if name == "get_current_time":
            return json.dumps({
                "datetime": "2026-08-28T10:30:00+01:00",
                "timezone": "WEST",
            })
        if name == "remember_user_fact":
            return json.dumps({"ok": True, "stored": args})
        if name == "get_functional_self_model":
            return json.dumps({"ok": True, "capabilities": ["conversation", "local tools"]})

        if name == "search_local_files":
            return json.dumps({"ok": True, "results": [
                {"name": "Python Notes.pdf", "path": "C:/Users/tiago/Documents/Python Notes.pdf", "extension": ".pdf"},
                {"name": "python.py", "path": "C:/Users/tiago/Documents/python.py", "extension": ".py"},
            ]})

        return json.dumps({"ok": False, "error": "UNKNOWN"})


class FastRouterTests(unittest.TestCase):
    def setUp(self):
        self.events = FakeEvents()
        self.tools = FakeTools()
        self.router = FastCommandRouter(
            self.events,
            self.tools,
            FakeApps(),
        )

    def test_open_app(self):
        result = self.router.dispatch("Jarvis, abre o Brave")
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "app_open")
        self.assertIn("Brave aberto", result.response)
        self.assertEqual(self.tools.calls[-1][0], "open_application")


    def test_voice_asr_open_repair_for_known_app(self):
        result = self.router.dispatch("Agrade o Brave", voice_origin=True)
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "voice_app_open_repair")
        self.assertEqual(self.tools.calls[-1][0], "open_application")

    def test_asr_repair_does_not_apply_to_typed_text(self):
        result = self.router.dispatch("Agrade o Brave", voice_origin=False)
        self.assertFalse(result.handled)

    def test_capability_question_uses_fast_path(self):
        result = self.router.dispatch("O que você pode fazer?")
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "capability_query")
        self.assertEqual(self.tools.calls[-1][0], "get_functional_self_model")

    def test_close_preserves_confirmation(self):
        result = self.router.dispatch("fecha o Brave")
        self.assertTrue(result.handled)
        self.assertIn("/confirm ABC123", result.response)

    def test_volume(self):
        result = self.router.dispatch("coloca o volume a 30%")
        self.assertTrue(result.handled)
        self.assertIn("30", result.response)

    def test_gpu_status(self):
        result = self.router.dispatch("qual é a temperatura atual da RTX")
        self.assertTrue(result.handled)
        self.assertIn("42", result.response)

    def test_time(self):
        result = self.router.dispatch("que horas são")
        self.assertTrue(result.handled)
        self.assertIn("10:30", result.response)

    def test_complex_question_falls_back(self):
        result = self.router.dispatch("Explica-me como funciona uma VPN")
        self.assertFalse(result.handled)

    def test_explicit_personal_memory_order_is_deterministic(self):
        result = self.router.dispatch(
            "Jarvis, o nome da minha mulher é ISA e quero que guardes essa informação na tua memória. Isto é uma ordem!"
        )
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "memory_write")
        self.assertEqual(self.tools.calls[-1][0], "remember_user_fact")
        self.assertEqual(
            self.tools.calls[-1][1]["fact"],
            "o nome da minha mulher é ISA",
        )
        self.assertIn("Guardado na memória local", result.response)

    def test_command_first_personal_memory_order(self):
        result = self.router.dispatch(
            "Quero que guardes na tua memória que a minha mulher se chama ISA."
        )
        self.assertTrue(result.handled)
        self.assertEqual(self.tools.calls[-1][0], "remember_user_fact")
        self.assertEqual(
            self.tools.calls[-1][1]["fact"],
            "a minha mulher se chama ISA",
        )

    def test_python_indentation_probe_is_valid_deterministic_code(self):
        result = self.router.dispatch("Jarvis, mostra apenas um exemplo Python indentado num bloco de código.")
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "python_indentation_probe")
        self.assertEqual(result.tool, "none")
        self.assertIn("    resultado = a + b", result.response)
        self.assertIn("    return resultado", result.response)

    def test_file_followups_without_previous_search_fail_closed(self):
        paths = self.router.dispatch("mostra os caminhos")
        self.assertTrue(paths.handled)
        self.assertEqual(paths.route, "local_file_followup_paths_empty")

        opened = self.router.dispatch("abre o primeiro")
        self.assertTrue(opened.handled)
        self.assertEqual(opened.route, "local_file_followup_open_first_empty")
        self.assertFalse(any(name == "open_application" for name, _ in self.tools.calls))

    def test_explicit_pdf_file_lookup_uses_local_index_not_book_library(self):
        result = self.router.dispatch("Jarvis, procura ficheiros PDF relacionados com Python.")
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "local_pdf_file_search")
        self.assertEqual(self.tools.calls[-1][0], "search_local_files")
        self.assertEqual(self.tools.calls[-1][1]["query"], "python")
        self.assertIn("Python Notes.pdf", result.response)

    def test_generic_file_save_is_not_memory_write(self):
        result = self.router.dispatch("guarda o ficheiro relatório na pasta documentos")
        self.assertFalse(result.handled)
        self.assertFalse(any(name == "remember_user_fact" for name, _ in self.tools.calls))


if __name__ == "__main__":
    unittest.main()
