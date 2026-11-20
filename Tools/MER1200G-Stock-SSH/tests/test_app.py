# SPDX-License-Identifier: MIT
"""Prove the single-command flow stops on failure without real SSH or networking."""
import contextlib
import hashlib
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


STAGES = ["prepare", "check", "rehearse", "verify_bundle", "flash", "restore"]


def run_main(arguments, *, failure=None, dependency=True, package_error=None):
    """All actions that could contact or modify the computer/router are mocked."""
    events = []
    output, errors = io.StringIO(), io.StringIO()

    def stage(name):
        events.append(name)
        if failure == name:
            raise RuntimeError("simulated " + name + " failure")
        if failure == "interrupt-rehearse" and name == "rehearse":
            raise KeyboardInterrupt()

    with contextlib.ExitStack() as stack:
        readers = stack.enter_context(patch.object(
            app, "read_package", return_value=({"image": {}}, {}), side_effect=package_error))
        work = stack.enter_context(patch.object(
            app, "open_workdir", return_value=Path("C:/offline-only-mocked-work")))
        network = stack.enter_context(patch.object(
            app, "network_action", side_effect=lambda action, *args: stage(action)))
        check = stack.enter_context(patch.object(
            app, "check", side_effect=lambda *args: stage("check")))
        controller = stack.enter_context(patch.object(
            app, "controller_action", side_effect=lambda action, *args: stage(action)))
        verify = stack.enter_context(patch.object(
            app, "verify_bundle", side_effect=lambda *args: stage("verify_bundle")))
        dependency_module = types.SimpleNamespace(__version__="3.5.1") if dependency else None
        stack.enter_context(patch.dict(sys.modules, {"paramiko": dependency_module}))
        stack.enter_context(patch.object(sys, "argv", ["offline-test.pyz", *arguments]))
        stack.enter_context(contextlib.redirect_stdout(output))
        stack.enter_context(contextlib.redirect_stderr(errors))
        code = 0
        try:
            app.main()
        except SystemExit as error:
            code = error.code
    return {"events": events, "code": code, "output": output.getvalue(), "errors": errors.getvalue(),
            "readers": readers, "work": work, "network": network, "check": check,
            "controller": controller, "verify": verify}


class AppStateMachineTests(unittest.TestCase):
    def test_install_success_restores_network_after_verified_flash(self):
        result = run_main(["install", "--direct-lan"])
        self.assertEqual(result["events"], STAGES)
        self.assertEqual(result["code"], 0)
        self.assertIn("INSTALL_COMPLETE", result["output"])

    def test_every_failure_stops_before_later_stages_without_retry(self):
        for failure in STAGES:
            with self.subTest(failure=failure):
                result = run_main(["install", "--direct-lan"], failure=failure)
                self.assertEqual(result["events"], STAGES[:STAGES.index(failure) + 1])
                self.assertEqual(result["code"], 1)
                self.assertIn("STOP: RuntimeError", result["errors"])
                self.assertNotIn("INSTALL_COMPLETE", result["output"])
                self.assertLessEqual(result["events"].count("rehearse"), 1)
                self.assertLessEqual(result["events"].count("flash"), 1)

    def test_interrupted_rehearsal_never_flashes_or_restores(self):
        result = run_main(["install", "--direct-lan"], failure="interrupt-rehearse")
        self.assertEqual(result["events"], ["prepare", "check", "rehearse"])
        self.assertEqual(result["code"], 1)
        self.assertIn("STOP: KeyboardInterrupt", result["errors"])

    def test_default_verification_never_opens_workdir_or_requires_ssh_dependency(self):
        result = run_main([], dependency=False)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["code"], 0)
        result["readers"].assert_called_once()
        result["work"].assert_not_called()
        self.assertIn("KIT_VERIFY_PASS", result["output"])

    def test_password_calculation_never_reads_package_or_network(self):
        result = run_main(["password", "--mac", "02:00:00:00:00:01"], dependency=False)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["output"].strip(), hashlib.md5(b"020000000001").hexdigest()[:8])
        result["readers"].assert_not_called()
        result["work"].assert_not_called()

    def test_invalid_mac_never_reads_package_or_network(self):
        result = run_main(["password", "--mac", "not-a-mac"], dependency=False)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["code"], 1)
        self.assertIn("Invalid stock LAN MAC", result["errors"])
        result["readers"].assert_not_called()
        result["work"].assert_not_called()

    def test_restore_works_without_paramiko_and_has_no_ssh_actions(self):
        result = run_main(["restore"], dependency=False)
        self.assertEqual(result["events"], ["restore"])
        self.assertEqual(result["code"], 0)
        result["controller"].assert_not_called()
        result["check"].assert_not_called()
        result["verify"].assert_not_called()

    def test_prepare_works_without_paramiko_and_has_no_ssh_actions(self):
        result = run_main(["prepare", "--direct-lan"], dependency=False)
        self.assertEqual(result["events"], ["prepare"])
        self.assertEqual(result["code"], 0)
        result["controller"].assert_not_called()
        result["check"].assert_not_called()

    def test_missing_ssh_dependency_stops_install_before_network_mutation(self):
        result = run_main(["install", "--direct-lan"], dependency=False)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["code"], 1)
        result["work"].assert_not_called()

    def test_changed_package_stops_before_network_or_workdir_actions(self):
        result = run_main(["install", "--direct-lan"], package_error=RuntimeError("changed package"))
        self.assertEqual(result["events"], [])
        self.assertEqual(result["code"], 1)
        result["work"].assert_not_called()
        self.assertIn("changed package", result["errors"])


if __name__ == "__main__":
    unittest.main()
