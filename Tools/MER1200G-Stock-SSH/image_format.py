#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate native MER1200G CI images before binding a stock SSH installer.

This accepts the current CI build rather than pinning one old release.  It is
an image/partition validator, not evidence that a new build has booted on hardware.
No router is contacted and no file is written by these functions.
"""
import hashlib
import json
import lzma
import re
import struct
import zlib

WINDOW_BYTES = 0xCF0000
ERASE_BYTES = 0x10000
PARTITIONS = [
    (0, 0x40000, "bootloader"), (0x40000, WINDOW_BYTES, "firmware"),
    (0xD30000, 0x10000, "device-info"), (0xD40000, 0x10000, "firmware-info"),
    (0xD50000, 0x10000, "tddp"), (0xD60000, 0x20000, "log"),
    (0xD80000, 0x70000, "reserved"), (0xDF0000, 0x200000, "rootfs-data-stock"),
    (0xFF0000, 0x10000, "art"),
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def align(value):
    return (value + ERASE_BYTES - 1) & ~(ERASE_BYTES - 1)


def parse_dtb(dtb):
    require(len(dtb) >= 40, "Truncated DTB")
    magic, total, off_struct, off_strings, _, version, compatible_version, _, strings_size, struct_size = struct.unpack_from(">10I", dtb)
    require(magic == 0xD00DFEED and 40 <= total <= len(dtb), "Invalid DTB envelope")
    require(version >= 17 and compatible_version <= 17, "Unsupported DTB version")
    require(40 <= off_struct <= total and 40 <= off_strings <= total, "DTB block offset")
    require(off_struct + struct_size <= total and off_strings + strings_size <= total, "DTB block out of bounds")
    require(off_struct + struct_size <= off_strings or off_strings + strings_size <= off_struct, "Overlapping DTB blocks")
    strings = dtb[off_strings:off_strings + strings_size]
    pos, end, stack, nodes = off_struct, off_struct + struct_size, [], {}
    while pos + 4 <= end:
        token = struct.unpack_from(">I", dtb, pos)[0]
        pos += 4
        if token == 1:
            stop = dtb.find(b"\0", pos, end)
            require(stop >= pos, "Unterminated DTB node")
            stack.append(dtb[pos:stop].decode("ascii"))
            pos = (stop + 4) & ~3
            path = "/" + "/".join(item for item in stack if item)
            require(path not in nodes, "Duplicate DTB node")
            nodes[path] = {}
        elif token == 2:
            require(bool(stack), "DTB stack underflow")
            stack.pop()
        elif token == 3:
            require(bool(stack) and pos + 8 <= end, "Invalid DTB property")
            length, nameoff = struct.unpack_from(">II", dtb, pos)
            pos += 8
            require(pos + length <= end and nameoff < len(strings), "DTB property out of bounds")
            stop = strings.find(b"\0", nameoff)
            require(stop > nameoff, "Unterminated DTB property name")
            name = strings[nameoff:stop].decode("ascii")
            props = nodes["/" + "/".join(item for item in stack if item)]
            require(name not in props, "Duplicate DTB property")
            props[name] = dtb[pos:pos + length]
            pos = (pos + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            require(not stack and "/" in nodes, "Unclosed or empty DTB")
            require(pos <= end and dtb[pos:end] == bytes(end - pos), "Trailing DTB structure tokens")
            return nodes
        else:
            raise ValueError("Invalid DTB token")
        require(pos <= end, "DTB alignment exceeds structure")
    raise ValueError("Missing DTB end token")


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "Duplicate firmware metadata key: " + key)
        value[key] = item
    return value


def _upgrade_metadata(firmware):
    require(len(firmware) >= 24, "Missing fwtool metadata")
    magic, crc, kind, reserved, length = struct.unpack_from(">IIB3sI", firmware, len(firmware) - 16)
    require(magic == 0x46577830 and kind == 1 and reserved == bytes(3), "Unsupported fwtool trailer")
    require(24 < length <= len(firmware), "Invalid fwtool metadata size")
    require(crc == (zlib.crc32(firmware[:-16]) ^ 0xFFFFFFFF), "fwtool image CRC mismatch")
    begin = len(firmware) - length
    require(firmware[begin:begin + 8] == bytes(8), "Unsupported fwtool metadata header")
    encoded = firmware[begin + 8:-16]
    require(0 < len(encoded) <= 0x10000, "Firmware metadata size outside bounds")
    metadata = json.loads(encoded.decode("utf-8"), object_pairs_hook=_unique_pairs)
    require(isinstance(metadata, dict) and metadata.get("metadata_version") == "1.1", "Unsupported firmware metadata version")
    require(metadata.get("supported_devices") == ["mercury,mer1200g-v1"], "Wrong upgrade supported_devices")
    version = metadata.get("version")
    require(isinstance(version, dict), "Missing firmware version")
    require(version.get("target") == "ramips/mt7620" and version.get("board") == "mercury_mer1200g-v1", "Wrong upgrade target/board")
    require(isinstance(version.get("dist"), str) and version["dist"].lower() == "immortalwrt", "Wrong firmware distribution")
    require(isinstance(version.get("revision"), str) and re.fullmatch(r"[A-Za-z0-9_.+\-]{1,128}", version["revision"]) is not None, "Invalid firmware revision")
    return begin, metadata


def inspect_sysupgrade(firmware):
    """Return verified native image metadata for exactly one complete sysupgrade."""
    require(isinstance(firmware, bytes) and 112 <= len(firmware) <= WINDOW_BYTES, "Invalid sysupgrade size/type")
    magic, hcrc, _, size, load, entry, dcrc, os_id, arch, kind, comp, name = struct.unpack_from(">7I4B32s", firmware)
    require(magic == 0x27051956 and zlib.crc32(firmware[:4] + bytes(4) + firmware[8:64]) == hcrc, "uImage header CRC")
    require((load, entry, os_id, arch, kind, comp) == (0x80000000, 0x80000400, 5, 5, 4, 3), "Unexpected uImage format")
    require(21 <= size < len(firmware) - 64, "uImage length")
    payload = firmware[64:64 + size]
    require(zlib.crc32(payload) == dcrc, "uImage data CRC")
    component, zero = struct.unpack_from(">II", payload)
    require(zero == 0 and component + 8 == size, "Expected one multi-uImage component")
    require(payload[8:13] == bytes.fromhex("6d00008000"), "LZMA properties")
    expanded = struct.unpack_from("<Q", payload, 13)[0]
    require(0x404 < expanded < 0x2000000, "Expanded kernel outside staging bounds")
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    raw = decoder.decompress(payload[8:], max_length=0x2000000)
    require(decoder.eof and not decoder.unused_data and len(raw) == expanded, "LZMA stream/size")
    insn = struct.unpack_from("<I", raw, 0x400)[0]
    jump = 0x80000000 | ((insn & 0x3FFFFFF) << 2)
    require(insn >> 26 == 2 and 0x80000000 <= jump < 0x80000000 + len(raw) and jump != 0x80000400, "Kernel entry trampoline")
    dtb_at = raw.rfind(bytes.fromhex("d00dfeed"))
    require(dtb_at >= 0, "Missing appended DTB")
    nodes = parse_dtb(raw[dtb_at:])
    require(b"mercury,mer1200g-v1" in nodes["/"].get("compatible", b"").split(b"\0"), "Wrong board")
    memories = [v for v in nodes.values() if v.get("device_type") == b"memory\0"]
    require(len(memories) == 1 and memories[0].get("reg") == struct.pack(">II", 0, 0x8000000), "Wrong memory")
    partition_nodes = []
    for path, props in nodes.items():
        if "/partitions/partition@" in path and path.rsplit("/", 1)[1].startswith("partition@"):
            require(len(props.get("reg", b"")) == 8 and props.get("label", b"").endswith(b"\0"), "Invalid native partition")
            reg = struct.unpack(">II", props["reg"])
            partition_nodes.append((reg, props))
    actual = sorted((reg[0], reg[1], props["label"][:-1].decode("ascii")) for reg, props in partition_nodes)
    require(actual == PARTITIONS, "Native partition whitelist mismatch")
    for reg, props in partition_nodes:
        require(("read-only" in props) == (reg[0] != 0x40000), "Unexpected flash write permission")
        if reg[0] == 0x40000:
            require(props.get("compatible") == b"openwrt,uimage\0denx,uimage\0" and props.get("openwrt,ih-type") == struct.pack(">I", 4), "Missing native multi-uImage partition parser")
    image_name = name.rstrip(b"\0").decode("ascii")
    prefix = "MER1200G Linux-"
    require(image_name.startswith(prefix), "Wrong uImage name")
    kernel_release = image_name[len(prefix):]
    require(re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[A-Za-z0-9_.+\-]*)", kernel_release) is not None and kernel_release.startswith("6."), "Unsupported kernel release")
    require(b"console=ttyS0,115200" in nodes.get("/chosen", {}).get("bootargs-override", b""), "Missing native bootargs override")
    root = align(64 + size)
    require(root + 96 < len(firmware), "Missing aligned rootfs")
    require(firmware[64 + size:root] == bytes(root - 64 - size), "Kernel alignment padding")
    require(firmware[root:root + 4] == b"hsqs", "Missing SquashFS")
    used = struct.unpack_from("<Q", firmware, root + 40)[0]
    require(96 <= used <= len(firmware) - root, "SquashFS bounds")
    overlay = align(root + used)
    require(overlay + 4 < len(firmware) and overlay < WINDOW_BYTES, "No fresh writable overlay space")
    require(firmware[root + used:overlay] == b"\xff" * (overlay - root - used), "Rootfs alignment padding")
    require(firmware[overlay:overlay + 4] == bytes.fromhex("deadc0de"), "Fresh overlay marker")
    metadata_start, metadata = _upgrade_metadata(firmware)
    require(metadata_start == overlay + 4, "Unexpected data between overlay marker and upgrade metadata")
    return {
        "profile": "native-ci-current", "kernel_release": kernel_release,
        "kernel_bytes": 64 + size, "rootfs_bytes": used, "rootfs_offset": root,
        "immutable_prefix_bytes": root + used, "immutable_prefix_sha256": sha(firmware[:root + used]),
        "blocks": WINDOW_BYTES // ERASE_BYTES, "overlay": "native-firstboot-marker", "overlay_offset": overlay,
        "sysupgrade_bytes": len(firmware), "sysupgrade_sha256": sha(firmware),
        "sysupgrade_metadata": metadata,
    }


def make_window(firmware):
    """Validate sysupgrade bytes and pad only the writable firmware window."""
    metadata = inspect_sysupgrade(firmware)
    window = firmware + b"\xff" * (WINDOW_BYTES - len(firmware))
    metadata["window_sha256"] = sha(window)
    return window, metadata


def validate_image(image):
    """Validate an already padded window and recover its exact sysupgrade size."""
    require(isinstance(image, bytes) and len(image) == WINDOW_BYTES, "Wrong 207-block window size")
    # A metadata length may itself end in FF, so rstrip() would remove real
    # trailer bytes. Locate the complete trailer and verify its following pad.
    position = len(image)
    while True:
        position = image.rfind(b"FWx0", 0, position)
        require(position >= 0, "No valid fwtool trailer before window padding")
        end = position + 16
        if end > len(image) or image[end:] != b"\xff" * (len(image) - end):
            continue
        try:
            metadata = inspect_sysupgrade(image[:end])
        except (ValueError, UnicodeError, struct.error, lzma.LZMAError):
            continue
        metadata["window_sha256"] = sha(image)
        return metadata
