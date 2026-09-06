import http.client
import inspect
import socket
import unittest
from unittest.mock import Mock, patch

from jarvis_core.services.local_research import (
    LocalResearchEngine,
    _PinnedHTTPHandler,
    _PinnedHTTPSHandler,
    _SafeRedirectHandler,
    _pinned_connection_factory,
)


class LocalResearchDnsPinningTests(
    unittest.TestCase
):
    def test_public_resolution_returns_validated_literal_ip(self):
        answer = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (
                    "93.184.216.34",
                    80,
                ),
            ),
        ]

        with patch(
            "jarvis_core.services.local_research.socket.getaddrinfo",
            return_value=answer,
        ):
            safe, addresses = (
                LocalResearchEngine
                ._resolve_public_target(
                    "http://rebind.example/path"
                )
            )

        self.assertEqual(
            safe,
            "http://rebind.example/path",
        )

        self.assertEqual(
            addresses,
            (
                "93.184.216.34",
            ),
        )


    def test_mixed_public_private_dns_answer_fails_closed(self):
        answer = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (
                    "93.184.216.34",
                    80,
                ),
            ),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (
                    "127.0.0.1",
                    80,
                ),
            ),
        ]

        with patch(
            "jarvis_core.services.local_research.socket.getaddrinfo",
            return_value=answer,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "PRIVATE_OR_LOCAL_TARGET_BLOCKED",
            ):
                (
                    LocalResearchEngine
                    ._resolve_public_target(
                        "http://mixed.example/"
                    )
                )


    def test_http_connection_uses_pinned_ip_and_preserves_origin_host(self):
        factory = (
            _pinned_connection_factory(
                http.client.HTTPConnection,
                (
                    "93.184.216.34",
                ),
            )
        )

        fake_socket = Mock()

        with patch(
            "jarvis_core.services.local_research.socket.create_connection",
            return_value=fake_socket,
        ) as create:
            connection = factory(
                "rebind.example:80",
                timeout=2,
            )

            connection.connect()

        self.assertEqual(
            connection.host,
            "rebind.example",
        )

        self.assertEqual(
            connection.port,
            80,
        )

        self.assertEqual(
            connection._jarvis_pinned_ips,
            (
                "93.184.216.34",
            ),
        )

        create.assert_called_once_with(
            (
                "93.184.216.34",
                80,
            ),
            2,
            None,
        )


    def test_https_connection_pins_ip_but_keeps_tls_sni_hostname(self):
        context = Mock()

        context.wrap_socket.return_value = (
            Mock()
        )

        factory = (
            _pinned_connection_factory(
                http.client.HTTPSConnection,
                (
                    "93.184.216.34",
                ),
            )
        )

        fake_socket = Mock()

        with patch(
            "jarvis_core.services.local_research.socket.create_connection",
            return_value=fake_socket,
        ) as create:
            connection = factory(
                "secure.example:443",
                timeout=2,
                context=context,
            )

            connection.connect()

        self.assertEqual(
            connection.host,
            "secure.example",
        )

        create.assert_called_once_with(
            (
                "93.184.216.34",
                443,
            ),
            2,
            None,
        )

        self.assertEqual(
            context.wrap_socket.call_args.kwargs[
                "server_hostname"
            ],
            "secure.example",
        )


    def test_get_uses_proxyless_pinned_handlers_and_safe_redirects(self):
        source = inspect.getsource(
            LocalResearchEngine._get
        )

        self.assertIn(
            "ProxyHandler({})",
            source,
        )

        self.assertIn(
            "_SafeRedirectHandler(",
            source,
        )

        self.assertIn(
            "_PinnedHTTPHandler(",
            source,
        )

        self.assertIn(
            "_PinnedHTTPSHandler(",
            source,
        )

        from urllib.request import (
            HTTPHandler,
            HTTPSHandler,
        )

        self.assertTrue(
            issubclass(
                _PinnedHTTPHandler,
                HTTPHandler,
            )
        )

        self.assertTrue(
            issubclass(
                _PinnedHTTPSHandler,
                HTTPSHandler,
            )
        )

        self.assertTrue(
            callable(
                _SafeRedirectHandler
            )
        )


if __name__ == "__main__":
    unittest.main()
