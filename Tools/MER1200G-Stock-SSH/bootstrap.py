# SPDX-License-Identifier: MIT
"""Authenticate and capture a new router's stock flash without remote writes.

This bootstrap deliberately does not use the old per-router install controller:
the original controller requires an already-bound backup and SSH host key.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess


FLASH_BYTES = 0x1000000
STOCK_START, STOCK_END = 0x40000, 0xD30000
HOST, PC_ADDRESS, NATIVE_PC_ADDRESS, SSH_PORT = (
    "192.168.2.50", "192.168.2.148", "192.168.1.148", 33400)
LAYOUT = [
    (0x40000, "bootloader"), (0x150000, "kernel"), (0xBA0000, "rootfs"),
    (0x10000, "device-info"), (0x10000, "firmware-info"),
    (0x10000, "tddp"), (0x20000, "log"), (0x200000, "rootfs_data"),
    (0x10000, "art"), (FLASH_BYTES, "firmware"),
]
IDENTITY_RANGES = [
    ("MER_BOOT_SHA", 0, 0x40000),
    ("MER_DEVICE_INFO_SHA", 0xD30000, 0xD40000),
    ("MER_FIRMWARE_INFO_SHA", 0xD40000, 0xD50000),
    ("MER_TDDP_SHA", 0xD50000, 0xD60000),
    ("MER_ART_SHA", 0xFF0000, FLASH_BYTES),
]
MODEL = {
    "manufacturer_name": "MERCURY", "model_name": "MER1200G",
    "model_id": "21200201", "model_version": "1.0",
}
BOOT_ID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
DEVICE_COMMAND = (
    "test -c /dev/mtd9 && test ! -L /dev/mtd9 && "
    "stat -c '%t %T' /dev/mtd9 && "
    "cat /sys/class/mtd/mtd9/type /sys/class/mtd/mtd9/size "
    "/sys/class/mtd/mtd9/erasesize /sys/class/mtd/mtd9/writesize "
    "/sys/class/mtd/mtd9/oobsize"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(key):
    return base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def windows_index():
    """Use the same one-wired-interface contract as the RAM-stage controller."""
    if os.name != "nt":
        return None
    script = (
        "Get-NetIPAddress -AddressFamily IPv4 -IPAddress " + PC_ADDRESS + "," +
        NATIVE_PC_ADDRESS + " -ErrorAction Stop | "
        "Select-Object IPAddress,InterfaceIndex | ConvertTo-Json -Compress")
    rows = json.loads(subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-Command", script]))
    require(isinstance(rows, list) and len(rows) == 2,
            "Both PC IPv4 aliases are required on the wired adapter")
    require({row["IPAddress"] for row in rows} == {PC_ADDRESS, NATIVE_PC_ADDRESS},
            "Wrong PC IPv4 aliases")
    indices = {row["InterfaceIndex"] for row in rows}
    require(len(indices) == 1 and all(isinstance(i, int) and i > 0 for i in indices),
            "PC aliases must identify one wired adapter")
    return next(iter(indices))


def connect_stock(workdir, host=HOST):
    """Trust one explicitly accepted, directly connected stock SSH server.

    Passwords never enter files or command arguments. The accepted key is not
    persisted until collect_stock has verified and saved the new backup.
    """
    del workdir  # No files are changed by the connection attempt.
    require(host == HOST, "This build requires stock LAN address " + HOST)
    import paramiko

    client = paramiko.SSHClient()
    accepted = {}

    class FirstConnection(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, ssh, hostname, key):
            value = fingerprint(key)
            print("New stock SSH host fingerprint: SHA256:" + value, flush=True)
            require(input("Trust this directly connected new router? Type yes: ").strip() == "yes",
                    "New router host key was not accepted")
            accepted["fingerprint"] = value
            ssh.get_host_keys().add(hostname, key.get_name(), key)

    client.set_missing_host_key_policy(FirstConnection())
    password = getpass.getpass("Stock root SSH password: ")
    sock = socket.socket()
    sock.settimeout(15)
    try:
        index = windows_index()
        if index is not None:
            sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack("!I", index))
        sock.bind((PC_ADDRESS, 0))
        sock.connect((host, SSH_PORT))
        client.connect(host, port=SSH_PORT, username="root", password=password,
                       sock=sock, allow_agent=False, look_for_keys=False,
                       timeout=15, banner_timeout=15, auth_timeout=20)
        transport = client.get_transport()
        require(transport is not None and transport.is_authenticated(),
                "Stock SSH is not authenticated")
        require(accepted.get("fingerprint") == fingerprint(transport.get_remote_server_key()),
                "Authenticated stock host key differs from the explicitly accepted key")
        return client
    except BaseException:
        sock.close()
        client.close()
        raise
    finally:
        password = None


def command(client, text, timeout=120):
    _, out, err = client.exec_command(text, timeout=timeout)
    data, error = out.read(), err.read()
    if out.channel.recv_exit_status():
        raise RuntimeError("Read-only router command failed: " + text + "; " +
                           error.decode("utf-8", "replace")[:300])
    return data


def parse_layout(data):
    lines = data.decode("ascii").strip().splitlines()
    require(len(lines) == 11 and lines[0].split() == ["dev:", "size", "erasesize", "name"],
            "Not the required original 10-partition stock table")
    result = []
    for number, line in enumerate(lines[1:]):
        match = re.fullmatch(r'mtd(\d+): ([0-9a-f]+) ([0-9a-f]+) "([^\"]+)"', line)
        require(match is not None, "Malformed original stock MTD row")
        index, size, erase, name = match.groups()
        size, erase = int(size, 16), int(erase, 16)
        require(int(index) == number and (size, name) == LAYOUT[number] and erase == 65536,
                "Original stock MTD geometry or labels differ")
        result.append({"index": number, "bytes": size, "erase_bytes": erase, "name": name})
    return result


def parse_geometry(data):
    lines = data.decode("ascii").strip().splitlines()
    require(len(lines) == 6, "Missing stock NOR device geometry")
    device = lines[0].split()
    require(len(device) == 2 and all(re.fullmatch(r"[0-9a-fA-F]+", p) for p in device),
            "Invalid stock MTD character-device numbers")
    require((int(device[0], 16), int(device[1], 16)) == (90, 18),
            "The stock full-flash device is not character device 90:18")
    require(lines[1] == "nor" and lines[2:] == [str(FLASH_BYTES), "65536", "1", "0"],
            "Stock full-flash device is not the required 16 MiB SPI NOR")
    return {"type": "nor", "bytes": FLASH_BYTES, "erase_bytes": 65536,
            "write_bytes": 1, "oob_bytes": 0, "major": 90, "minor": 18}


def model_from_backup(raw):
    require(len(raw) == FLASH_BYTES, "Short or oversized stock full-flash backup")
    # The original device-info partition carries its device JSON after the
    # 16-byte envelope. Do not search an arbitrary image for a model substring.
    text = raw[0xD30000 + 16:0xD40000].decode("utf-8", "replace")
    try:
        identity, _ = json.JSONDecoder().raw_decode(text)
    except (ValueError, TypeError) as error:
        raise RuntimeError("Stock device-info does not contain the expected device JSON") from error
    require(isinstance(identity, dict) and all(identity.get(k) == v for k, v in MODEL.items()),
            "Stock identity is not the supported MERCURY MER1200G v1")
    # The device-info also contains a public key. Store only these public model
    # fields in the report; preserve the complete original bytes in the backup.
    return dict(MODEL)


def hashes(raw):
    require(len(raw) == FLASH_BYTES, "Short or oversized stock full-flash read")
    return {
        "stock_region_sha256": sha(raw[STOCK_START:STOCK_END]),
        "protected": {name: sha(raw[start:end]) for name, start, end in IDENTITY_RANGES},
    }


def save_json_exclusive(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(value, out, indent=2, ensure_ascii=False)
        out.write("\n")


def collect_stock(workdir, host=HOST, *, supported_stock_sha256,
                  connect_fn=None, command_fn=None):
    """Save and bind a previously unknown router's authenticated stock backup.

    A work directory may already contain a network preparation snapshot; the
    backup, report and accepted SSH host key must all be new files. A failed
    capture never grants a bundle or a flashing permit.
    """
    require(host == HOST, "This build requires stock LAN address " + HOST)
    require(not isinstance(supported_stock_sha256, (str, bytes)),
            "A nonempty supported stock SHA256 list is required")
    try:
        supported = tuple(supported_stock_sha256)
    except TypeError as error:
        raise RuntimeError("A nonempty supported stock SHA256 list is required") from error
    require(supported and all(isinstance(value, str) and
                             re.fullmatch(r"[0-9a-f]{64}", value) for value in supported),
            "A nonempty supported stock SHA256 list of lowercase 64-hex hashes is required")
    supported = set(supported)
    workdir = Path(workdir).resolve()
    workdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_path, report_path, known_path = (
        workdir / "full-flash.bin", workdir / "stock-bootstrap.json", workdir / "known_hosts")
    require(not any(p.exists() or p.is_symlink() for p in (backup_path, report_path, known_path)),
            "Work directory already contains a stock identity or backup; use a new directory")
    connect_fn = connect_stock if connect_fn is None else connect_fn
    command_fn = command if command_fn is None else command_fn
    result = {
        "format": "mer1200g-new-stock-backup-v1", "passed": False,
        "host": host, "ssh_port": SSH_PORT,
        "scope": "Authenticated read-only new-device inspection and full-flash backup",
        "uploads": False, "services_changed": False, "flash": False,
        "ready_for_flashing": False, "router_contacted": False,
        "supported_stock_sha256": sorted(supported),
    }
    client = None
    try:
        client = connect_fn(workdir, host)
        result["router_contacted"] = True
        transport = client.get_transport()
        require(transport is not None and transport.is_authenticated(), "Stock SSH is not authenticated")
        key = transport.get_remote_server_key()
        result.update(stock_host_fingerprint=fingerprint(key),
                      stock_host_key_sha256=sha(key.asbytes()))
        boot = command_fn(client, "cat /proc/sys/kernel/random/boot_id").decode("ascii").strip()
        require(re.fullmatch(BOOT_ID, boot) is not None, "Invalid stock boot ID")
        result["boot_id"] = boot
        result["layout"] = parse_layout(command_fn(client, "cat /proc/mtd"))
        result["geometry"] = parse_geometry(command_fn(client, DEVICE_COMMAND))
        release = command_fn(client, "uname -r").decode("ascii").strip()
        require(release.startswith("3.10."), "Required original stock kernel family is Linux 3.10")
        result["kernel"] = release
        memory = command_fn(client, "cat /proc/meminfo").decode("ascii")
        values = {k: int(v) for k, v in re.findall(r"^(\w+):\s+(\d+) kB", memory, re.M)}
        require(120000 <= values.get("MemTotal", 0) <= 131072,
                "Required original stock environment has 128 MiB RAM")
        available = values.get("MemAvailable", values.get("MemFree", 0) +
                               values.get("Cached", 0) + values.get("Buffers", 0) -
                               values.get("Shmem", 0))
        require(available >= 64 * 1024, "Need at least 64 MiB estimated available RAM before staging")
        result["estimated_available_kib"] = available
        space = command_fn(client, "df -k /tmp").decode("ascii").splitlines()
        require(len(space) >= 2, "Missing /tmp free-space report")
        columns = space[-1].split()
        require(len(columns) >= 6 and columns[3].isdigit() and int(columns[3]) >= 18 * 1024,
                "Need at least 18 MiB free space in /tmp")

        first = command_fn(client, "cat /dev/mtd9", 180)
        result["model"] = model_from_backup(first)
        baseline = hashes(first)
        with backup_path.open("xb") as out:
            require(out.write(first) == FLASH_BYTES, "Short local full-flash backup write")
            out.flush()
            os.fsync(out.fileno())
        require(backup_path.stat().st_size == FLASH_BYTES and sha(backup_path.read_bytes()) == sha(first),
                "Saved local full-flash backup differs from the authenticated read")
        result.update(backup_path=str(backup_path), backup_bytes=FLASH_BYTES,
                      backup_sha256=sha(first), **baseline)
        print("Saved new-router full-flash backup: " + str(backup_path), flush=True)
        second = command_fn(client, "cat /dev/mtd9", 180)
        require(hashes(second) == baseline,
                "Stock firmware or protected identity changed between the two full-flash reads")
        require(model_from_backup(second) == result["model"], "Stock device identity changed during capture")
        boot_after = command_fn(client, "cat /proc/sys/kernel/random/boot_id").decode("ascii").strip()
        require(boot_after == boot, "Stock router rebooted during backup capture")
        # Configuration and logs are mutable while stock is running. They are
        # preserved in the first full-flash snapshot but do not authorize writes.
        result["mutable_regions_changed_during_read"] = (
            first[0xD60000:0xFF0000] != second[0xD60000:0xFF0000])
        require(transport.is_authenticated() and fingerprint(transport.get_remote_server_key()) ==
                result["stock_host_fingerprint"], "Authenticated stock SSH identity changed")
        require(baseline["stock_region_sha256"] in supported,
                "Stock firmware window is not in this installer's supported stock SHA256 list; "
                "backup saved, read-only compatibility review required")
        with known_path.open("x", encoding="ascii", newline="\n") as out:
            out.write(f"[{host}]:{SSH_PORT} {key.get_name()} {key.get_base64()}\n")
        result.update(passed=True, result="NEW_STOCK_BACKUP_PASS", boot_id_unchanged=True,
                      immutable_reads_match=True, known_hosts_path=str(known_path))
        save_json_exclusive(report_path, result)
        print("NEW_STOCK_BACKUP_PASS: new device identity and full-flash backup verified; "
              "ready_for_flashing=false", flush=True)
        return result
    except BaseException as error:
        result.update(passed=False, result="FAILED", error=type(error).__name__ + ": " + str(error))
        if not report_path.exists():
            save_json_exclusive(report_path, result)
        raise
    finally:
        if client is not None:
            client.close()
