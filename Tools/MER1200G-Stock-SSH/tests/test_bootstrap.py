# SPDX-License-Identifier: MIT
"""Exercise rejected devices and changing flash over fake authenticated SSH."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap


class FakeKey:
    def asbytes(self):
        return b"new-router-test-host-key"

    def get_name(self):
        return "ssh-rsa"

    def get_base64(self):
        return base64.b64encode(self.asbytes()).decode()


class FakeClient:
    def __init__(self, *, authenticated=True):
        self.authenticated = authenticated
        self.closed = False

    def get_transport(self):
        return self

    def get_remote_server_key(self):
        return FakeKey()

    def is_authenticated(self):
        return self.authenticated

    def close(self):
        self.closed = True


def original_flash():
    raw = bytearray(b"\xff" * bootstrap.FLASH_BYTES)
    raw[:0x40000] = bytes(range(256)) * 1024
    info = json.dumps(bootstrap.MODEL).encode("ascii")
    raw[0xD30000 + 16:0xD30000 + 16 + len(info)] = info
    return bytes(raw)


SUPPORTED_STOCK_SHA256 = [bootstrap.sha(original_flash()[bootstrap.STOCK_START:bootstrap.STOCK_END])]


class FakeRouter:
    def __init__(self):
        self.client = FakeClient()
        self.first = original_flash()
        self.second = self.first
        self.boot = "01234567-89ab-cdef-0123-456789abcdef"
        self.after_boot = self.boot
        self.kernel = "3.10.14"
        self.memory = b"MemTotal: 126000 kB\nMemFree: 70000 kB\nCached: 5000 kB\nBuffers: 5000 kB\nShmem: 0 kB\n"
        self.geometry = b"5a 12\nnor\n16777216\n65536\n1\n0\n"
        self.layout = ("dev:    size   erasesize  name\n" + "".join(
            f'mtd{i}: {size:08x} 00010000 "{name}"\n'
            for i, (size, name) in enumerate(bootstrap.LAYOUT))).encode("ascii")
        self.commands = []
        self.flash_reads = 0
        self.boot_reads = 0

    def connect(self, workdir, host):
        assert host == bootstrap.HOST
        return self.client

    def command(self, client, text, timeout=120):
        assert client is self.client
        self.commands.append(text)
        if text == "cat /proc/sys/kernel/random/boot_id":
            self.boot_reads += 1
            return ((self.boot if self.boot_reads == 1 else self.after_boot) + "\n").encode()
        if text == "cat /proc/mtd":
            return self.layout
        if text == bootstrap.DEVICE_COMMAND:
            return self.geometry
        if text == "uname -r":
            return (self.kernel + "\n").encode()
        if text == "cat /proc/meminfo":
            return self.memory
        if text == "df -k /tmp":
            return b"Filesystem 1K-blocks Used Available Use% Mounted on\ntmpfs 60000 1000 59000 2% /tmp\n"
        if text == "cat /dev/mtd9":
            self.flash_reads += 1
            return self.first if self.flash_reads == 1 else self.second
        raise AssertionError("Unexpected remote operation: " + text)


class BootstrapTests(unittest.TestCase):
    def test_vendor_busybox_numeric_device_listing(self):
        raw = (b"crw-r--r--    1 0        0          90,  18 Jan  1  1970 /dev/mtd9\n"
               b"nor\n16777216\n65536\n1\n0\n")
        self.assertEqual(bootstrap.parse_geometry(raw)["major"], 90)
        self.assertEqual(bootstrap.parse_geometry(raw)["minor"], 18)

    def test_numeric_listing_rejects_wrong_node_or_geometry(self):
        row = b"crw-r--r-- 1 0 0 90, 18 Jan 1 1970 /dev/mtd9"
        suffix = b"\nnor\n16777216\n65536\n1\n0\n"
        for invalid in [row.replace(b"90, 18", b"90, 16"),
                        row.replace(b"90, 18", b"91, 18"),
                        row.replace(b"crw", b"brw"),
                        row.replace(b"crw", b"lrw"),
                        row.replace(b"/dev/mtd9", b"/dev/mtd8"),
                        row + b" -> /dev/mtd8",
                        row.replace(b"90, 18", b"garbage"),
                        row + b"\n" + row]:
            with self.subTest(row=invalid), self.assertRaises(RuntimeError):
                bootstrap.parse_geometry(invalid + suffix)
        with self.assertRaises(RuntimeError):
            bootstrap.parse_geometry(row + suffix.replace(b"nor", b"nand"))

    def capture(self, root, router):
        return bootstrap.collect_stock(root, supported_stock_sha256=SUPPORTED_STOCK_SHA256,
                                       connect_fn=router.connect, command_fn=router.command)

    def test_valid_new_device_backup_and_key_are_bound(self):
        router = FakeRouter()
        with tempfile.TemporaryDirectory() as root:
            result = self.capture(root, router)
            self.assertTrue(result["passed"])
            self.assertFalse(result["ready_for_flashing"])
            self.assertEqual(Path(result["backup_path"]).read_bytes(), router.first)
            self.assertEqual(result["stock_host_fingerprint"], bootstrap.fingerprint(FakeKey()))
            self.assertEqual(router.flash_reads, 2)
            self.assertEqual(json.loads((Path(root) / "stock-bootstrap.json").read_text())["passed"], True)
            self.assertTrue((Path(root) / "known_hosts").read_text().startswith("[192.168.2.50]:33400 ssh-rsa "))
            self.assertTrue(router.client.closed)

    def test_changed_mutable_config_is_allowed_and_first_snapshot_is_preserved(self):
        router = FakeRouter()
        second = bytearray(router.first)
        second[0xDF0000] ^= 1
        router.second = bytes(second)
        with tempfile.TemporaryDirectory() as root:
            result = self.capture(root, router)
            self.assertTrue(result["mutable_regions_changed_during_read"])
            self.assertEqual(Path(result["backup_path"]).read_bytes(), router.first)

    def test_changed_firmware_or_protected_region_never_grants_a_bundle(self):
        for position in [0x40000, 0, 0xD40000, 0xFF0000]:
            with self.subTest(position=position), tempfile.TemporaryDirectory() as root:
                router = FakeRouter()
                second = bytearray(router.first)
                second[position] ^= 1
                router.second = bytes(second)
                with self.assertRaisesRegex(RuntimeError, "changed between"):
                    self.capture(root, router)
                report = json.loads((Path(root) / "stock-bootstrap.json").read_text())
                self.assertFalse(report["passed"])
                self.assertFalse((Path(root) / "known_hosts").exists())
                self.assertEqual((Path(root) / "full-flash.bin").read_bytes(), router.first)

    def test_new_boot_during_read_is_rejected(self):
        router = FakeRouter()
        router.after_boot = "11234567-89ab-cdef-0123-456789abcdef"
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "rebooted during"):
                self.capture(root, router)
            self.assertFalse((Path(root) / "known_hosts").exists())

    def test_short_read_is_rejected(self):
        router = FakeRouter()
        router.first = router.first[:-1]
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "Short or oversized"):
                self.capture(root, router)
            self.assertFalse((Path(root) / "full-flash.bin").exists())

    def test_wrong_partition_geometry_is_rejected_before_flash_read(self):
        router = FakeRouter()
        router.layout = router.layout.replace(b'"rootfs"', b'"other"')
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "geometry or labels"):
                self.capture(root, router)
            self.assertEqual(router.flash_reads, 0)

    def test_wrong_device_type_major_size_or_erase_is_rejected(self):
        for geometry in [b"5a 10\nnor\n16777216\n65536\n1\n0\n",
                         b"5a 12\nnand\n16777216\n65536\n1\n0\n",
                         b"5a 12\nnor\n33554432\n65536\n1\n0\n",
                         b"5a 12\nnor\n16777216\n4096\n1\n0\n"]:
            with self.subTest(geometry=geometry), tempfile.TemporaryDirectory() as root:
                router = FakeRouter()
                router.geometry = geometry
                with self.assertRaises(RuntimeError):
                    self.capture(root, router)
                self.assertEqual(router.flash_reads, 0)

    def test_wrong_model_is_rejected_without_persisting_a_trusted_key(self):
        router = FakeRouter()
        raw = bytearray(router.first)
        raw[0xD30000:0xD40000] = b"\xff" * 0x10000
        identity = dict(bootstrap.MODEL, model_name="OTHER")
        text = json.dumps(identity).encode()
        raw[0xD30000 + 16:0xD30000 + 16 + len(text)] = text
        router.first = bytes(raw)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "not the supported"):
                self.capture(root, router)
            self.assertFalse((Path(root) / "full-flash.bin").exists())
            self.assertFalse((Path(root) / "known_hosts").exists())

    def test_wrong_kernel_or_memory_budget_is_rejected_before_flash_read(self):
        for change in ["kernel", "memory"]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as root:
                router = FakeRouter()
                if change == "kernel":
                    router.kernel = "6.18.60"
                else:
                    router.memory = b"MemTotal: 250000 kB\nMemAvailable: 70000 kB\n"
                with self.assertRaises(RuntimeError):
                    self.capture(root, router)
                self.assertEqual(router.flash_reads, 0)

    def test_unauthenticated_ssh_is_rejected_before_commands(self):
        router = FakeRouter()
        router.client.authenticated = False
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "not authenticated"):
                self.capture(root, router)
            self.assertEqual(router.commands, [])
            self.assertTrue(router.client.closed)

    def test_existing_backup_is_never_overwritten_or_contacted(self):
        router = FakeRouter()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "full-flash.bin"
            path.write_bytes(b"do not overwrite")
            with self.assertRaisesRegex(RuntimeError, "already contains"):
                self.capture(root, router)
            self.assertEqual(path.read_bytes(), b"do not overwrite")
            self.assertFalse(router.client.closed)
            self.assertEqual(router.commands, [])

    def test_wrong_host_is_rejected_without_local_or_remote_changes(self):
        router = FakeRouter()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "requires stock LAN address"):
                bootstrap.collect_stock(root, host="192.168.1.1", connect_fn=router.connect,
                                        command_fn=router.command,
                                        supported_stock_sha256=SUPPORTED_STOCK_SHA256)
            self.assertEqual(list(Path(root).iterdir()), [])
            self.assertEqual(router.commands, [])

    def test_unknown_stock_version_preserves_backup_but_never_binds_a_key(self):
        router = FakeRouter()
        raw = bytearray(router.first)
        raw[bootstrap.STOCK_START] ^= 1
        router.first = router.second = bytes(raw)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "not in this installer's supported"):
                self.capture(root, router)
            self.assertEqual(router.flash_reads, 2)
            self.assertEqual((Path(root) / "full-flash.bin").read_bytes(), router.first)
            self.assertFalse((Path(root) / "known_hosts").exists())
            report = json.loads((Path(root) / "stock-bootstrap.json").read_text())
            self.assertFalse(report["passed"])
            self.assertFalse(report["ready_for_flashing"])
            self.assertEqual(report["supported_stock_sha256"], SUPPORTED_STOCK_SHA256)
            self.assertNotIn(report["stock_region_sha256"], SUPPORTED_STOCK_SHA256)
            self.assertTrue(router.client.closed)

    def test_missing_or_invalid_stock_allowlist_is_rejected_before_connection(self):
        for supported in [[], (), None, "a" * 64, ["not-a-sha256"], ["A" * 64], ["a" * 63]]:
            with self.subTest(supported=supported), tempfile.TemporaryDirectory() as root:
                router = FakeRouter()
                with self.assertRaisesRegex(RuntimeError, "nonempty supported stock SHA256 list"):
                    bootstrap.collect_stock(root, supported_stock_sha256=supported,
                                            connect_fn=router.connect, command_fn=router.command)
                self.assertEqual(list(Path(root).iterdir()), [])
                self.assertEqual(router.commands, [])
                self.assertFalse(router.client.closed)


if __name__ == "__main__":
    unittest.main()
