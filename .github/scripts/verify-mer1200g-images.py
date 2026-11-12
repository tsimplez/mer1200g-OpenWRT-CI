#!/usr/bin/env python3
"""Check the MER1200G image envelope, capacity and required installed features."""
import argparse
import hashlib
import json
import lzma
import struct
import zlib
from pathlib import Path

FIRMWARE_START = 0x40000
FIRMWARE_SIZE = 0xCF0000
ERASE = 0x10000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def align(value):
    return (value + ERASE - 1) // ERASE * ERASE


def inspect(path, ram):
    data = path.read_bytes()
    require(len(data) >= 85, f"{path.name}: truncated header")
    magic, hcrc, epoch, size, load, entry, dcrc, os, arch, kind, comp, name = struct.unpack_from(">7I4B32s", data)
    require(magic == 0x27051956 and len(data) >= 64 + size, "invalid uImage size/magic")
    require(zlib.crc32(data[:4] + bytes(4) + data[8:64]) == hcrc, "uImage header CRC mismatch")
    payload = data[64:64 + size]
    require(zlib.crc32(payload) == dcrc, "uImage data CRC mismatch")
    require((load, entry, os, arch, kind, comp) == (0x80000000, 0x80000400, 5, 5, 4, 3), "unexpected vendor image format")
    require(len(payload) >= 21, "truncated multi-uImage payload")
    component, end = struct.unpack_from(">II", payload)
    require(component + 8 == size and end == 0, "expected exactly one multi-uImage component")
    compressed = payload[8:]
    require(compressed[:5] == bytes.fromhex("6d00008000"), "unexpected LZMA properties")
    expanded_size = struct.unpack_from("<Q", compressed, 5)[0]
    require(0 < expanded_size < 0x2000000, "expanded image overlaps TFTP staging address")
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    expanded = decoder.decompress(compressed, max_length=0x2000000)
    require(decoder.eof and not decoder.unused_data and len(expanded) == expanded_size, "invalid LZMA stream/length")
    result = {
        "file": path.name, "sha256": hashlib.sha256(data).hexdigest(), "file_bytes": len(data),
        "kernel_uimage_bytes": 64 + size, "expanded_bytes": expanded_size,
        "image_name": name.rstrip(b"\0").decode("ascii"), "epoch": epoch, "ram_only": ram,
    }
    if ram:
        require(len(data) == 64 + size, "RAM image has trailing data")
    else:
        root = align(64 + size)
        require(len(data) >= root + 96 and data[root:root + 4] == b"hsqs", "aligned SquashFS missing")
        used_root = struct.unpack_from("<Q", data, root + 40)[0]
        require(96 <= used_root <= len(data) - root, "SquashFS length outside image")
        used = align(root + used_root)
        require(used < FIRMWARE_SIZE and len(data) <= FIRMWARE_SIZE, "firmware does not fit with writable space")
        require(data[used:used + 4] == bytes.fromhex("deadc0de"), "overlay initialization marker missing")
        result.update({
            "firmware_window_bytes": FIRMWARE_SIZE,
            "rootfs_flash_start": hex(FIRMWARE_START + root), "squashfs_bytes": used_root,
            "overlay_flash_start": hex(FIRMWARE_START + used),
            "overlay_available_bytes": FIRMWARE_SIZE - used,
            "overlay_available_mib": (FIRMWARE_SIZE - used) / 1024**2,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    normal = list(args.directory.glob("*mercury_mer1200g-v1*squashfs-sysupgrade.bin"))
    ram = list(args.directory.glob("*mercury_mer1200g-v1*RAM-ONLY.bin"))
    manifests = list(args.directory.glob("*mercury_mer1200g-v1.manifest"))
    require(len(normal) == len(ram) == len(manifests) == 1, "expected exactly one MER1200G image pair and manifest")
    installed = {line.split()[0] for line in manifests[0].read_text().splitlines() if line.strip()}
    required = {
        "luci-base", "luci-i18n-base-zh-cn", "luci-theme-vantage", "luci-i18n-vantage-theme-zh-cn",
        "dropbear", "firewall4", "dnsmasq-full", "ppp-mod-pppoe",
        "kmod-mt76x2", "kmod-rt2800-soc", "kmod-switch-rtl8367b",
    }
    require(required <= installed, "missing installed packages: " + ", ".join(sorted(required - installed)))
    report = {"status": "PASS_STATIC_IMAGES", "persistent": inspect(normal[0], False),
              "ram": inspect(ram[0], True), "required_packages": sorted(required),
              "scope": "image structure and installed packages; not a hardware boot or upgrade test"}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
