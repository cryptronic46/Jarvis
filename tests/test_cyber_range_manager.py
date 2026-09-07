import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jarvis_core.services.cyber_range as cyber_range
from jarvis_core.services.cyber_range import CyberRangeManager


class CyberRangeManagerTests(unittest.TestCase):
    def make_manager(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = CyberRangeManager(Path(tmp.name) / "range.json")
        return manager

    def test_private_target_is_not_lab_by_default(self):
        manager = self.make_manager()
        result = manager.classify("192.168.56.10")
        self.assertEqual(result["scope"], "PRIVATE_UNAUTHORIZED")
        self.assertFalse(result["authorized"])

    def test_owner_cli_can_add_private_lab_scope(self):
        manager = self.make_manager()
        added = manager.add_lab_scope("192.168.56.0/24", "VirtualBox Lab")
        self.assertTrue(added["ok"])
        result = manager.classify("192.168.56.10")
        self.assertEqual(result["scope"], "LAB")
        self.assertTrue(result["authorized"])
        self.assertEqual(result["label"], "VirtualBox Lab")

    def test_public_scope_cannot_be_added(self):
        manager = self.make_manager()
        result = manager.add_lab_scope("8.8.8.8")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "LAB_SCOPE_MUST_BE_PRIVATE")

    def test_scope_cannot_be_too_broad(self):
        manager = self.make_manager()
        result = manager.add_lab_scope("10.0.0.0/8")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "LAB_SCOPE_TOO_BROAD")

    def test_owner_machine_beats_lab_network(self):
        manager = self.make_manager()
        manager.add_lab_scope("192.168.56.0/24")
        with patch.object(manager, "_owner_addresses", return_value={"192.168.56.1"}):
            result = manager.classify("192.168.56.1")
        self.assertEqual(result["scope"], "OWNER_MACHINE")
        self.assertFalse(result["authorized"])

    def test_probe_is_blocked_until_target_is_lab(self):
        manager = self.make_manager()
        result = manager.probe("192.168.56.10", [22])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "TARGET_NOT_AUTHORIZED_LAB")

    def test_probe_is_bounded_and_only_reports_connectivity(self):
        manager = self.make_manager()
        manager.add_lab_scope(
            "192.168.56.10",
            "Metasploitable",
        )

        class ExactGuardian:
            def __init__(self):
                self.calls = []

            def consume_direct_authorization(
                self,
                *,
                execution_token,
                capability,
                payload,
            ):
                self.calls.append({
                    "execution_token":
                        execution_token,
                    "capability":
                        capability,
                    "payload":
                        dict(payload),
                })

                return {
                    "ok": (
                        execution_token
                        == "TEST-NETWORK-TOKEN"
                        and capability
                        == "active_network_probe"
                    ),
                    "allowed": (
                        execution_token
                        == "TEST-NETWORK-TOKEN"
                        and capability
                        == "active_network_probe"
                    ),
                }

        guardian = ExactGuardian()
        manager.authority_guardian = guardian

        class DummyConnection:
            def close(self):
                pass

        def fake_connect(addr, timeout):
            if addr[1] == 22:
                return DummyConnection()
            raise OSError("closed")

        with patch(
            "jarvis_core.services.cyber_range.socket.create_connection",
            side_effect=fake_connect,
        ):
            result = manager.probe(
                "192.168.56.10",
                [22, 80],
                execution_token=
                    "TEST-NETWORK-TOKEN",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["open_ports"],
            [22],
        )
        self.assertEqual(
            result[
                "closed_or_filtered_ports"
            ],
            [80],
        )
        self.assertEqual(
            result["probe"],
            "tcp_connect",
        )

        self.assertEqual(
            len(guardian.calls),
            1,
        )
        self.assertEqual(
            guardian.calls[0][
                "capability"
            ],
            "active_network_probe",
        )
        self.assertEqual(
            guardian.calls[0][
                "payload"
            ]["ports"],
            [22, 80],
        )


class CyberRangeToolAuthorityTests(
    unittest.TestCase
):
    def setUp(self):
        self.tmp = (
            tempfile.TemporaryDirectory()
        )
        self.addCleanup(
            self.tmp.cleanup
        )

        self.previous_manager = (
            cyber_range._MANAGER
        )

        self.addCleanup(
            self._restore_manager
        )

    def _restore_manager(self):
        cyber_range._MANAGER = (
            self.previous_manager
        )

    def test_tool_wrapper_requests_exact_authority_and_blocks_replay(
        self,
    ):
        class DummyConnection:
            def close(self):
                pass

        class ExactToolGuardian:
            def __init__(self):
                self.mode = "pending"
                self.request_payload = None
                self.consumed = False
                self.requests = []

            def request(
                self,
                *,
                capability,
                payload,
                reason,
                description,
                action,
                source,
            ):
                self.request_payload = dict(
                    payload
                )

                self.requests.append({
                    "capability":
                        capability,
                    "payload":
                        dict(payload),
                    "reason":
                        reason,
                    "action":
                        action,
                    "source":
                        source,
                })

                if self.mode == "pending":
                    return {
                        "ok": True,
                        "allowed": False,
                        "pending": True,
                        "token":
                            "PENDING-TEST",
                    }

                return {
                    "ok": True,
                    "allowed": True,
                    "execution_token":
                        "RUNTIME-TEST",
                }

            def consume_direct_authorization(
                self,
                *,
                execution_token,
                capability,
                payload,
            ):
                if (
                    execution_token
                    != "RUNTIME-TEST"
                    or capability
                    != "active_network_probe"
                    or payload
                    != self.request_payload
                ):
                    return {
                        "ok": False,
                        "allowed": False,
                        "error":
                            "SCOPE_MISMATCH",
                    }

                if self.consumed:
                    return {
                        "ok": False,
                        "allowed": False,
                        "error":
                            "TOKEN_REPLAY",
                    }

                self.consumed = True

                return {
                    "ok": True,
                    "allowed": True,
                }

        guardian = ExactToolGuardian()

        manager = CyberRangeManager(
            Path(self.tmp.name)
            / "range.json",
            authority_guardian=guardian,
        )

        self.assertTrue(
            manager.add_lab_scope(
                "10.255.254.123/32",
                "Tool authority test",
            )["ok"]
        )

        cyber_range.set_cyber_range_manager(
            manager
        )

        socket_calls = []

        def fake_connect(
            address,
            timeout=None,
        ):
            socket_calls.append(
                (address, timeout)
            )
            return DummyConnection()

        with patch(
            "jarvis_core.services."
            "cyber_range.socket."
            "create_connection",
            side_effect=fake_connect,
        ):
            pending = (
                cyber_range
                .probe_cyber_lab_target(
                    "10.255.254.123",
                    [443],
                )
            )

            self.assertFalse(
                pending["ok"]
            )
            self.assertEqual(
                pending["error"],
                "OWNER_AUTHORIZATION_REQUIRED",
            )
            self.assertEqual(
                socket_calls,
                [],
            )

            self.assertEqual(
                guardian.requests[0][
                    "capability"
                ],
                "active_network_probe",
            )
            self.assertEqual(
                guardian.requests[0][
                    "action"
                ],
                "probe_cyber_lab_target",
            )
            self.assertEqual(
                guardian.requests[0][
                    "source"
                ],
                "cyber_range_tool",
            )

            guardian.mode = "allowed"

            allowed = (
                cyber_range
                .probe_cyber_lab_target(
                    "10.255.254.123",
                    [443],
                )
            )

            self.assertTrue(
                allowed["ok"]
            )
            self.assertTrue(
                guardian.consumed
            )
            self.assertEqual(
                len(socket_calls),
                1,
            )

            replay = (
                cyber_range
                .probe_cyber_lab_target(
                    "10.255.254.123",
                    [443],
                    execution_token=
                        "RUNTIME-TEST",
                )
            )

            self.assertFalse(
                replay["ok"]
            )
            self.assertEqual(
                replay["error"],
                (
                    "OWNER_AUTHORIZED_"
                    "NETWORK_SCOPE_INVALID"
                ),
            )

            self.assertEqual(
                len(socket_calls),
                1,
            )


if __name__ == "__main__":
    unittest.main()
