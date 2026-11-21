# SPDX-License-Identifier: MIT
"""SSH failures preserve the error and close the transport before its socket."""
from pathlib import Path
import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap
import controller


class SSHConnectionTests(unittest.TestCase):
    def check_connection(self, module, function, *, empty=False):
        events = []
        client, sock = MagicMock(), MagicMock()
        failure = RuntimeError("authentication rejected")
        client.connect.side_effect = failure
        client.close.side_effect = lambda: events.append("transport")
        sock.close.side_effect = lambda: events.append("socket")
        paramiko = types.SimpleNamespace(SSHClient=lambda: client, MissingHostKeyPolicy=object)
        with patch.dict(sys.modules, {"paramiko": paramiko}), \
                patch.object(module.getpass, "getpass", return_value="" if empty else "test-password"), \
                patch.object(module.socket, "socket", return_value=sock) as socket_factory, \
                patch.object(module, "windows_index", return_value=None), \
                patch.object(controller, "stock_fingerprint", return_value="test-fingerprint"):
            with self.assertRaises(RuntimeError) as caught:
                function(Path("offline-test"))
        if empty:
            self.assertIn("password is empty", str(caught.exception))
            socket_factory.assert_not_called()
            client.connect.assert_not_called()
        else:
            self.assertIs(caught.exception, failure)
            client.connect.assert_called_once()
            sock.connect.assert_called_once()
            self.assertEqual(events, ["transport", "socket"])

    def test_bootstrap_failure_closes_transport_first_without_retry(self):
        self.check_connection(bootstrap, bootstrap.connect_stock)

    def test_controller_failure_closes_transport_first_without_retry(self):
        self.check_connection(controller, controller.connect)

    def test_empty_bootstrap_password_never_connects(self):
        self.check_connection(bootstrap, bootstrap.connect_stock, empty=True)

    def test_empty_controller_password_never_connects(self):
        self.check_connection(controller, controller.connect, empty=True)

    def test_native_password_is_still_entered_manually(self):
        with patch.object(bootstrap, "stock_password", side_effect=AssertionError("must not calculate native password")) as calculate:
            self.check_connection(controller, lambda path: controller.connect(path, native=True))
        calculate.assert_not_called()

    def neighbor(self):
        return dict(IPAddress=bootstrap.HOST, InterfaceIndex=4,
                    LinkLayerAddress="bc-54-fc-76-9e-2b", State="Reachable")

    def test_wired_neighbor_calculates_the_verified_password_without_prompting(self):
        with patch.object(bootstrap.subprocess, "check_output", return_value=json.dumps(self.neighbor()).encode()) as read, \
                patch.object(bootstrap.getpass, "getpass", side_effect=AssertionError("no manual stock prompt")):
            self.assertEqual(bootstrap.stock_password(4), "5049939d")
        self.assertIn("-InterfaceIndex 4", read.call_args.args[0][-1])

    def test_ambiguous_invalid_or_wrong_interface_neighbor_is_rejected(self):
        row = self.neighbor()
        invalid = [[], [row, row], dict(row, IPAddress="192.168.1.1"),
                   dict(row, InterfaceIndex=18), dict(row, State="Unreachable"),
                   dict(row, LinkLayerAddress="00-00-00-00-00-00"),
                   dict(row, LinkLayerAddress="FF-FF-FF-FF-FF-FF"),
                   dict(row, LinkLayerAddress="not-a-mac"), None]
        for data in invalid:
            with self.subTest(data=data), \
                    patch.object(bootstrap.subprocess, "check_output", return_value=json.dumps(data).encode()), \
                    self.assertRaises(RuntimeError):
                bootstrap.stock_password(4)

    def test_fresh_arp_is_resolved_by_tcp_before_stock_password_lookup(self):
        for module, function in [(bootstrap, bootstrap.connect_stock), (controller, controller.connect)]:
            with self.subTest(module=module.__name__):
                events = []
                client, sock = MagicMock(), MagicMock()
                failure = RuntimeError("stop before any router command")
                sock.connect.side_effect = lambda address: events.append("tcp")
                def calculate(index):
                    self.assertEqual(index, 4)
                    self.assertEqual(events, ["tcp"])
                    events.append("password")
                    return "auto-password"
                def authenticate(*args, **kwargs):
                    self.assertEqual(kwargs["password"], "auto-password")
                    events.append("ssh")
                    raise failure
                client.connect.side_effect = authenticate
                paramiko = types.SimpleNamespace(SSHClient=lambda: client, MissingHostKeyPolicy=object)
                with patch.dict(sys.modules, {"paramiko": paramiko}), \
                        patch.object(module.socket, "socket", return_value=sock), \
                        patch.object(module, "windows_index", return_value=4), \
                        patch.object(bootstrap, "stock_password", side_effect=calculate), \
                        patch.object(controller, "stock_fingerprint", return_value="test-fingerprint"), \
                        self.assertRaises(RuntimeError) as caught:
                    function(Path("offline-test"))
                self.assertIs(caught.exception, failure)
                self.assertEqual(events, ["tcp", "password", "ssh"])
                client.close.assert_called_once()
                sock.close.assert_called_once()

    def test_failed_tcp_never_reads_stock_mac_or_authenticates(self):
        for module, function in [(bootstrap, bootstrap.connect_stock), (controller, controller.connect)]:
            with self.subTest(module=module.__name__):
                client, sock = MagicMock(), MagicMock()
                sock.connect.side_effect = OSError("router unreachable")
                paramiko = types.SimpleNamespace(SSHClient=lambda: client, MissingHostKeyPolicy=object)
                with patch.dict(sys.modules, {"paramiko": paramiko}), \
                        patch.object(module.socket, "socket", return_value=sock), \
                        patch.object(module, "windows_index", return_value=4), \
                        patch.object(bootstrap, "stock_password") as calculate, \
                        patch.object(controller, "stock_fingerprint", return_value="test-fingerprint"), \
                        self.assertRaises(OSError):
                    function(Path("offline-test"))
                calculate.assert_not_called()
                client.connect.assert_not_called()
                sock.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
