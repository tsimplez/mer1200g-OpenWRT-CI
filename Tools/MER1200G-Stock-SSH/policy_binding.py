# SPDX-License-Identifier: MIT
"""Bind a reviewed, separate ELF policy section; never patch executable code."""
import hashlib
import json
import secrets
import struct
from pathlib import Path

MAGIC = b'MERPOLICY-V1\0\0\0\0'
POLICY_BYTES = 748
SHA_NAMES = ('image', 'backup', 'stock', 'boot', 'deviceinfo', 'firmwareinfo', 'tddp', 'art')
HELPERS = ('stock-preflight.mipsel', 'snapshot.mipsel', 'preflight.mipsel', 'writer.mipsel')
PROTECTED = {
    'MER_BOOT_SHA': ('boot', 0, 0x40000),
    'MER_DEVICE_INFO_SHA': ('deviceinfo', 0xd30000, 0xd40000),
    'MER_FIRMWARE_INFO_SHA': ('firmwareinfo', 0xd40000, 0xd50000),
    'MER_TDDP_SHA': ('tddp', 0xd50000, 0xd60000),
    'MER_ART_SHA': ('art', 0xff0000, 0x1000000),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def policy_span(elf):
    require(len(elf) >= 52 and elf[:7] == b'\x7fELF\x01\x01\x01', 'Expected ELF32 little-endian')
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', elf)
    require(h[1] == 2 and h[2] == 8 and h[3] == 1, 'Expected MIPS executable')
    require(h[7] & 0xf0000000 == 0x70000000 and h[7] & 0xf000 == 0x1000 and
            not h[7] & 0x20, 'Expected MIPS32r2 O32 profile')
    require(h[8] == 52 and h[11] == 40 and 0 < h[12] <= 1024 and h[13] < h[12],
            'Invalid ELF section table')
    require(h[9] == 32 and 0 < h[10] <= 64, 'Invalid ELF program table')
    require(h[5] + h[9] * h[10] <= len(elf) and h[6] + h[11] * h[12] <= len(elf),
            'Truncated ELF tables')
    sections = [struct.unpack_from('<10I', elf, h[6] + 40 * n) for n in range(h[12])]
    names_section = sections[h[13]]
    require(names_section[1] == 3 and names_section[4] + names_section[5] <= len(elf), 'ELF names')
    names = elf[names_section[4]:names_section[4] + names_section[5]]
    found, abi = [], []
    for s in sections:
        require(s[0] < len(names), 'Invalid ELF section name')
        end = names.find(b'\0', s[0])
        require(end >= 0, 'Unterminated ELF section name')
        if names[s[0]:end] == b'.mer_policy':
            found.append(s)
        if names[s[0]:end] == b'.MIPS.abiflags':
            abi.append(s)
    require(len(abi) == 1 and abi[0][5] == 24 and abi[0][4] + 24 <= len(elf), 'Missing MIPS ABI flags')
    abi_flags = struct.unpack_from('<HBBBBBBIIII', elf, abi[0][4])
    require(abi_flags[:7] == (0, 32, 2, 1, 0, 0, 3), 'Expected O32 soft-float ABI')
    require(len(found) == 1, 'Exactly one policy section required')
    s = found[0]
    require(s[1] == 1 and s[2] == 2 and s[5] == POLICY_BYTES and s[8] == 4,
            'Policy must be a readonly allocated data section')
    offset, size = s[4], s[5]
    require(offset + size <= len(elf), 'Truncated ELF policy')
    programs = [struct.unpack_from('<8I', elf, h[5] + 32 * n) for n in range(h[10])]
    require(not any(p[0] in (2, 3) for p in programs), 'Helper must be statically linked')
    abi_programs = [p for p in programs if p[0] == 0x70000003]
    require(len(abi_programs) == 1 and abi_programs[0][1] == abi[0][4] and
            abi_programs[0][4:6] == (24, 24) and abi_programs[0][6] == 4,
            'MIPS ABI section must match its readonly runtime program header')
    for p in programs:
        if p[0] == 1:
            require(p[4] <= p[5] and p[1] + p[4] <= len(elf), 'Invalid loaded segment bounds')
    require(any(p[0] == 1 and p[6] & 1 and p[2] <= h[4] < p[2] + p[4] for p in programs),
            'Entry point is not executable')
    require(any(p[0] == 1 and p[1] <= offset and offset + size <= p[1] + p[4]
                and p[2] + offset - p[1] == s[3] and p[6] & 4 and not p[6] & 2 for p in programs),
            'Policy is not in a readonly loaded segment')
    require(elf[offset:offset + 24] == struct.pack('<16sII', MAGIC, 1, POLICY_BYTES),
            'Unknown policy schema')
    return offset, size


def encode_policy(hashes, nonces, helper_files=None):
    helper_files = helper_files or {}
    fields = struct.pack('<16sIIII', MAGIC, 1, POLICY_BYTES,
                         len(helper_files.get(HELPERS[0], b'')), len(helper_files.get(HELPERS[1], b'')))
    for name in SHA_NAMES:
        value = hashes[name]
        require(len(value) == 64 and all(c in '0123456789abcdef' for c in value), 'Invalid policy hash')
        fields += value.encode('ascii') + b'\0'
    for name in ('preflight', 'write'):
        value = nonces[name]
        require(len(value) == 32 and all(c in '0123456789abcdef' for c in value), 'Invalid nonce')
        fields += value.encode('ascii') + b'\0'
    for name in HELPERS[:2]:
        value = sha(helper_files[name]) if name in helper_files else '?' * 64
        fields += value.encode('ascii') + b'\0'
    require(len(fields) == POLICY_BYTES, 'Policy serialization length')
    return fields


def require_template(template):
    offset, size = policy_span(template)
    require(template[offset + 24:offset + 32] == bytes(8), 'Template already has helper sizes')
    sentinel = b'?' * 64 + b'\0'
    require(template[offset + 32:offset + 552] == sentinel * 8 and
            template[offset + 552:offset + 618] == (b'?' * 32 + b'\0') * 2 and
            template[offset + 618:offset + size] == sentinel * 2, 'Template is already bound')
    return offset, size


def bind_one(template, policy):
    offset, size = require_template(template)
    require(len(policy) == size, 'Wrong binding size')
    result = template[:offset] + policy + template[offset + size:]
    require(policy_span(result) == (offset, size) and len(result) == len(template), 'ELF binding changed structure')
    return result


def make_bundle(templates, image, image_metadata, stock, output):
    from network_contract import NETWORK
    from protocol_contract import STATUS_PROTOCOL
    require(set(templates) == set(HELPERS), 'Incomplete helper template set')
    backup = Path(stock['backup_path']).read_bytes()
    require(len(backup) == 0x1000000 and sha(backup) == stock['backup_sha256'], 'Backup changed after capture')
    require(len(image) == 0xcf0000 and image_metadata['window_sha256'] == sha(image), 'Image identity')
    hashes = {'image': sha(image), 'backup': sha(backup), 'stock': sha(backup[0x40000:0xd30000])}
    protected = {}
    for key, (name, start, end) in PROTECTED.items():
        hashes[name] = protected[key] = sha(backup[start:end])
    require(protected == stock['protected'] and hashes['stock'] == stock['stock_region_sha256'],
            'Stock identity changed after capture')
    nonces = {'preflight': secrets.token_hex(16), 'write': secrets.token_hex(16)}
    base = encode_policy(hashes, nonces)
    files = {name: bind_one(templates[name], base) for name in HELPERS[:2]}
    stage = encode_policy(hashes, nonces, files)
    files.update({name: bind_one(templates[name], stage) for name in HELPERS[2:]})
    files['image.bin'] = image
    manifest = {
        'format': 'mer1200g-stock-ssh-v2', 'private_per_device': True,
        'target_profile': 'native-ci-current', 'backup_sha256': hashes['backup'],
        'stock_region_sha256': hashes['stock'], 'stock_host_fingerprint': stock['stock_host_fingerprint'],
        'protected': protected, 'nonce': nonces, 'image': image_metadata,
        'files': {name: {'bytes': len(data), 'sha256': sha(data)} for name, data in files.items()},
        'geometry': {'flash': 0x1000000, 'start': 0x40000, 'end': 0xd30000, 'erase': 65536, 'blocks': 207},
        'network': dict(NETWORK), 'status_protocol': STATUS_PROTOCOL,
        'hardware_stock_to_native_tested': False,
    }
    output = Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    known = Path(stock['backup_path']).parent / 'known_hosts'
    (output / 'known_hosts').write_bytes(known.read_bytes())
    return manifest
