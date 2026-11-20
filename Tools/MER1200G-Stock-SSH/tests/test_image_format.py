# SPDX-License-Identifier: MIT
"""Native-image regression tests using a public CI sysupgrade fixture.

Run on Linux with MER1200G_SYSUPGRADE=/path/to/*squashfs-sysupgrade.bin.
Without that environment variable the fixture-dependent cases are skipped.
No per-device backup, identity, router access or flash operation is involved.
"""
import copy
import importlib.util
import json
import lzma
import os
from pathlib import Path
import struct
import unittest
import zlib

MODULE = Path(__file__).resolve().parents[1] / "image_format.py"
SPEC = importlib.util.spec_from_file_location("stock_test_image_format", MODULE)
image_format = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image_format)


@unittest.skipUnless(os.environ.get("MER1200G_SYSUPGRADE"), "Set MER1200G_SYSUPGRADE to a public CI sysupgrade fixture")
class NativeImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.firmware = Path(os.environ["MER1200G_SYSUPGRADE"]).read_bytes()
        cls.metadata = image_format.inspect_sysupgrade(cls.firmware)
        trailer_size = struct.unpack_from(">I", cls.firmware, len(cls.firmware) - 4)[0]
        cls.metadata_start = len(cls.firmware) - trailer_size
        cls.json_bytes = cls.firmware[cls.metadata_start + 8:-16]
        cls.upgrade = json.loads(cls.json_bytes)
        cls.prefix = cls.firmware[:cls.metadata_start]

    @staticmethod
    def append_metadata(prefix, encoded):
        payload = prefix + bytes(8) + encoded
        return payload + struct.pack(">IIB3sI", 0x46577830, zlib.crc32(payload) ^ 0xFFFFFFFF,
                                     1, bytes(3), len(encoded) + 24)

    def assert_valid(self, firmware):
        window, metadata = image_format.make_window(firmware)
        self.assertEqual(len(window), image_format.WINDOW_BYTES)
        self.assertEqual(image_format.validate_image(window), metadata)
        return metadata

    def test_public_ci_firmware_round_trip(self):
        self.assertEqual(self.assert_valid(self.firmware)["sysupgrade_bytes"], len(self.firmware))

    def test_new_revision_has_no_old_release_hash_dependency(self):
        upgrade = copy.deepcopy(self.upgrade)
        upgrade["version"]["revision"] = "r12345-new-ci-build"
        changed = self.append_metadata(self.prefix, json.dumps(upgrade).encode())
        metadata = self.assert_valid(changed)
        self.assertNotEqual(metadata["sysupgrade_sha256"], self.metadata["sysupgrade_sha256"])
        self.assertEqual(metadata["sysupgrade_metadata"]["version"]["revision"], "r12345-new-ci-build")

    def test_metadata_size_ending_in_ff_is_not_trimmed(self):
        encoded = json.dumps(self.upgrade).encode()
        encoded += b" " * ((255 - (len(encoded) + 24)) % 256)
        self.assertEqual((len(encoded) + 24) % 256, 255)
        self.assert_valid(self.append_metadata(self.prefix, encoded))

    def test_wrong_supported_device_even_with_correct_crc(self):
        upgrade = copy.deepcopy(self.upgrade)
        upgrade["supported_devices"] = ["mercury,mer1200g-v2"]
        changed = self.append_metadata(self.prefix, json.dumps(upgrade).encode())
        with self.assertRaisesRegex(ValueError, "supported_devices"):
            image_format.inspect_sysupgrade(changed)

    def test_duplicate_json_key_even_with_correct_crc(self):
        body = self.json_bytes.rstrip()
        self.assertEqual(body[-1:], b"}")
        body = body[:-1] + b', "metadata_version": "1.1"}\n'
        # It is valid JSON, so rejection specifically tests ambiguous keys.
        self.assertEqual(json.loads(body)["metadata_version"], "1.1")
        changed = self.append_metadata(self.prefix, body)
        with self.assertRaisesRegex(ValueError, "Duplicate firmware metadata key"):
            image_format.inspect_sysupgrade(changed)

    def test_kernel_corruption_after_recomputing_outer_crc(self):
        changed = bytearray(self.firmware)
        changed[90] ^= 1
        changed = self.append_metadata(bytes(changed[:self.metadata_start]), self.json_bytes)
        with self.assertRaisesRegex(ValueError, "uImage data CRC"):
            image_format.inspect_sysupgrade(changed)

    def test_corrupted_fwtool_trailer(self):
        changed = bytearray(self.firmware)
        changed[-15] ^= 1
        with self.assertRaisesRegex(ValueError, "fwtool trailer"):
            image_format.inspect_sysupgrade(bytes(changed))

    def test_corrupted_window_padding(self):
        window, _ = image_format.make_window(self.firmware)
        changed = bytearray(window)
        changed[-100] = 0
        with self.assertRaises(ValueError):
            image_format.validate_image(bytes(changed))

    def test_wrong_art_dtb_partition_with_valid_compression_and_crcs(self):
        size = struct.unpack_from(">I", self.firmware, 12)[0]
        raw = lzma.decompress(self.firmware[72:64 + size], format=lzma.FORMAT_ALONE)
        dtb_at = raw.rfind(bytes.fromhex("d00dfeed"))
        self.assertGreaterEqual(dtb_at, 0)
        dtb = raw[dtb_at:]
        original_reg = struct.pack(">II", 0xFF0000, 0x10000)
        self.assertEqual(dtb.count(original_reg), 1)
        raw = raw[:dtb_at] + dtb.replace(original_reg, struct.pack(">II", 0xFE0000, 0x10000))
        compressed = lzma.compress(raw, format=lzma.FORMAT_ALONE, filters=[{
            "id": lzma.FILTER_LZMA1, "dict_size": 0x800000, "lc": 1, "lp": 2, "pb": 2,
        }])
        compressed = compressed[:5] + struct.pack("<Q", len(raw)) + compressed[13:]
        payload = struct.pack(">II", len(compressed), 0) + compressed
        header = bytearray(self.firmware[:64])
        struct.pack_into(">I", header, 12, len(payload))
        struct.pack_into(">I", header, 24, zlib.crc32(payload))
        struct.pack_into(">I", header, 4, 0)
        struct.pack_into(">I", header, 4, zlib.crc32(header))
        head = bytes(header) + payload
        root = image_format.align(len(head))
        rootfs = self.firmware[self.metadata["rootfs_offset"]:
                              self.metadata["rootfs_offset"] + self.metadata["rootfs_bytes"]]
        prefix = head + bytes(root - len(head)) + rootfs
        prefix += b"\xff" * (image_format.align(len(prefix)) - len(prefix)) + bytes.fromhex("deadc0de")
        changed = self.append_metadata(prefix, self.json_bytes)
        with self.assertRaisesRegex(ValueError, "partition whitelist"):
            image_format.inspect_sysupgrade(changed)


if __name__ == "__main__":
    unittest.main()
