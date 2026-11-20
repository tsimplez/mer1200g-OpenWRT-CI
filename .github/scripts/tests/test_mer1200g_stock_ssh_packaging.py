# SPDX-License-Identifier: MIT
"""Exercise the CI packaging contract with isolated, fake compiler/build inputs.

These Linux/bash tests never compile firmware, contact a router or publish assets.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "package-mer1200g.sh"
ARTIFACT = "immortalwrt-ramips-mt7620-mercury_mer1200g-v1-stock-ssh-installer.pyz"


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Packaging tests require Linux/bash")
class PackageIntegrationTests(unittest.TestCase):
    @staticmethod
    def file(root, name, text, executable=False):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if executable:
            path.chmod(0o755)
        return path

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mer-ci-stock-package-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ci = self.root / "ci"
        self.wrt = self.root / "wrt"
        self.ci.mkdir()
        self.wrt.mkdir()
        for name in [".config", "bin/targets/ramips/mt7620/immortalwrt-ramips-mt7620-mercury_mer1200g-v1-squashfs-sysupgrade.bin",
                     "bin/targets/ramips/mt7620/ram.RAM-ONLY.bin"]:
            self.file(self.wrt, name, "mock image")
        self.file(self.ci, "build-reports/mer1200g-source.txt", "source")
        self.file(self.ci, "build-reports/mer1200g-source.json", "{}")
        self.file(self.ci, "build-reports/mer1200g-theme.json", "{}")
        self.file(self.ci, "Patches/MER1200G/source.json", json.dumps({"device_patch_sha256": "abc"}))
        self.file(self.ci, "Config/MER1200G-theme.json", json.dumps({"version": "v1", "commit": "abc"}))
        self.file(self.ci, ".github/scripts/verify-mer1200g-images.py",
                  'import pathlib,sys;pathlib.Path(sys.argv[sys.argv.index("--output")+1]).write_text("{}")\n')
        self.file(self.wrt, "staging_dir/host/bin/fwtool",
                  '#!/usr/bin/env python3\nimport pathlib,sys;pathlib.Path(sys.argv[2]).write_text(\'{"supported_devices":["mercury,mer1200g-v1"]}\')\n', True)
        self.compiler = self.file(self.wrt, "staging_dir/toolchain-1/bin/mipsel-openwrt-linux-musl-gcc",
                                  "#!/bin/sh\nexit 0\n", True)
        self.builder = self.file(self.ci, "Tools/MER1200G-Stock-SSH/build_installer.py",
                                 'import os,pathlib,sys,json\n'
                                 'p=pathlib.Path(sys.argv[sys.argv.index("--output")+1]);p.write_bytes(b"zipapp");'
                                 'pathlib.Path("builder-args.json").write_text(json.dumps({"args":sys.argv[1:],"staging":os.environ["STAGING_DIR"]}))\n')
        self.verifier = self.file(self.ci, "Tools/MER1200G-Stock-SSH/verify_installer.py",
                                  'import os,pathlib,sys,json\n'
                                  'p=pathlib.Path(sys.argv[sys.argv.index("--output")+1]);'
                                  'p.write_text(json.dumps({"passed":True,"hardware_tested":False,"router_accessed":False,"checks":[]}));'
                                  'pathlib.Path("verifier-args.json").write_text(json.dumps({"args":sys.argv[1:],"staging":os.environ["STAGING_DIR"]}))\n')
        self.unit_test = self.file(self.ci, "Tools/MER1200G-Stock-SSH/tests/test_fixture.py",
                                   'import os,json,pathlib,unittest\n'
                                   'class FixtureTests(unittest.TestCase):\n'
                                   ' def test_current_firmware_environment(self):\n'
                                   '  value=os.environ["MER1200G_SYSUPGRADE"]\n'
                                   '  self.assertTrue(pathlib.Path(value).is_file())\n'
                                   '  pathlib.Path("unit-env.json").write_text(json.dumps({"image":value}))\n')
        self.env = dict(os.environ, GITHUB_WORKSPACE=str(self.ci), WRT_REPO="repo", WRT_BRANCH="owrt",
                        WRT_HASH="abc", WRT_TEST="false")

    def run_package(self):
        return subprocess.run(["bash", "-c", SCRIPT.read_text(encoding="utf-8")], cwd=self.wrt,
                              env=self.env, capture_output=True, text=True)

    def assert_failed_before_checksums(self):
        result = self.run_package()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.wrt / "upload/SHA256SUMS").exists())

    def test_success_includes_single_package_in_checksums(self):
        result = self.run_package()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        artifact = self.wrt / "upload" / ARTIFACT
        self.assertTrue(artifact.is_file())
        checksum = hashlib.sha256(artifact.read_bytes()).hexdigest() + "  " + ARTIFACT
        self.assertIn(checksum, (self.wrt / "upload/SHA256SUMS").read_text())
        args = json.loads((self.wrt / "builder-args.json").read_text())
        self.assertEqual(args["staging"], str(self.wrt / "staging_dir"))
        self.assertEqual(args["args"][args["args"].index("--cc") + 1], str(self.compiler))
        verify = json.loads((self.wrt / "verifier-args.json").read_text())
        self.assertEqual(verify["staging"], str(self.wrt / "staging_dir"))
        self.assertEqual(verify["args"][verify["args"].index("--package") + 1], "upload/" + ARTIFACT)
        self.assertEqual(verify["args"][verify["args"].index("--cc") + 1], str(self.compiler))
        self.assertEqual(verify["args"][verify["args"].index("--output") + 1],
                         str(self.ci / "build-reports/mer1200g-stock-ssh-offline.json"))
        report = self.wrt / "upload/mer1200g-stock-ssh-offline.json"
        self.assertTrue(json.loads(report.read_text())["passed"])
        self.assertIn(hashlib.sha256(report.read_bytes()).hexdigest() + "  " + report.name,
                      (self.wrt / "upload/SHA256SUMS").read_text())
        unit = json.loads((self.wrt / "unit-env.json").read_text())
        self.assertEqual(unit["image"], str(self.wrt / "bin/targets/ramips/mt7620/immortalwrt-ramips-mt7620-mercury_mer1200g-v1-squashfs-sysupgrade.bin"))
        self.assertIn("stock-ssh-installer.pyz", (self.ci / "build-reports/mer1200g-release.md").read_text())

    def test_config_only_run_has_no_install_package(self):
        self.env["WRT_TEST"] = "true"
        result = self.run_package()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.wrt / "upload" / ARTIFACT).exists())
        self.assertFalse((self.wrt / "verifier-args.json").exists())
        self.assertFalse((self.wrt / "unit-env.json").exists())
        self.assertFalse((self.wrt / "upload/mer1200g-stock-ssh-offline.json").exists())

    def test_missing_cross_compiler(self):
        self.compiler.unlink()
        self.assert_failed_before_checksums()

    def test_ambiguous_cross_compiler(self):
        self.file(self.wrt, "staging_dir/toolchain-2/bin/mipsel-openwrt-linux-musl-gcc", "#!/bin/sh\nexit 0\n", True)
        self.assert_failed_before_checksums()

    def test_nonexecutable_cross_compiler(self):
        self.compiler.chmod(0o644)
        self.assert_failed_before_checksums()

    def test_failed_builder(self):
        self.builder.write_text("raise SystemExit(9)\n")
        self.assert_failed_before_checksums()

    def test_builder_does_not_produce_artifact(self):
        self.builder.write_text("pass\n")
        self.assert_failed_before_checksums()

    def test_failed_offline_verifier_prevents_publication(self):
        self.verifier.write_text("raise SystemExit(7)\n")
        self.assert_failed_before_checksums()
        self.assertTrue((self.wrt / "upload" / ARTIFACT).exists())
        self.assertFalse((self.wrt / "unit-env.json").exists())
        self.assertFalse((self.ci / "build-reports/mer1200g-release.md").exists())

    def test_verifier_does_not_produce_report(self):
        self.verifier.write_text("pass\n")
        self.assert_failed_before_checksums()
        self.assertFalse((self.ci / "build-reports/mer1200g-release.md").exists())

    def failed_report(self, fields):
        self.verifier.write_text('import pathlib,sys,json\n'
                                 'p=pathlib.Path(sys.argv[sys.argv.index("--output")+1]);'
                                 'p.write_text(json.dumps(' + repr(fields) + '))\n')
        self.assert_failed_before_checksums()
        self.assertFalse((self.wrt / "unit-env.json").exists())
        self.assertFalse((self.wrt / "upload/mer1200g-stock-ssh-offline.json").exists())
        self.assertFalse((self.ci / "build-reports/mer1200g-release.md").exists())

    def test_verifier_report_failed_despite_exit_zero(self):
        self.failed_report({"passed": False, "hardware_tested": False, "router_accessed": False})

    def test_verifier_report_claims_router_access(self):
        self.failed_report({"passed": True, "hardware_tested": False, "router_accessed": True})

    def test_verifier_report_claims_hardware_testing(self):
        self.failed_report({"passed": True, "hardware_tested": True, "router_accessed": False})

    def test_verifier_report_has_no_router_scope(self):
        self.failed_report({"passed": True, "hardware_tested": False})

    def test_verifier_report_passed_is_numeric_instead_of_boolean(self):
        self.failed_report({"passed": 1, "hardware_tested": False, "router_accessed": False})

    def test_failed_unit_tests_prevent_publication(self):
        self.unit_test.write_text('import unittest\nclass FailTests(unittest.TestCase):\n def test_failure(self): self.fail("intentional gate test")\n')
        self.assert_failed_before_checksums()
        self.assertTrue((self.ci / "build-reports/mer1200g-stock-ssh-offline.json").exists())
        self.assertFalse((self.ci / "build-reports/mer1200g-release.md").exists())


if __name__ == "__main__":
    unittest.main()
