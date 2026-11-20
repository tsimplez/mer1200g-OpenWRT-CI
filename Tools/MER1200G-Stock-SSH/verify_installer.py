#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline checks only: synthetic device identities, memory NOR and QEMU."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from app import read_package
from policy_binding import HELPERS, PROTECTED, bind_one, encode_policy, policy_span, sha

HERE = Path(__file__).resolve().parent


def verify(package_path, cc, qemu='qemu-mipsel', host_cc='gcc'):
    package, assets = read_package(package_path)
    image = assets['assets/window.bin']
    records = []

    def run(name, argv, expected=0, timeout=300):
        completed = subprocess.run([str(v) for v in argv], capture_output=True, text=True,
                                   timeout=timeout, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1'})
        if completed.returncode != expected:
            raise RuntimeError(name + ': exit ' + str(completed.returncode) + '\n' +
                               completed.stdout[-1200:] + completed.stderr[-2000:])
        records.append({'name': name, 'passed': True, 'exit': expected})
        print('PASS ' + name, flush=True)
        return completed

    with tempfile.TemporaryDirectory(prefix='mer1200g-offline-') as temporary:
        temporary = Path(temporary)
        image_path = temporary / 'image.bin'
        image_path.write_bytes(image)
        bad_path = temporary / 'bad-image.bin'
        bad = bytearray(image)
        bad[64] ^= 1
        bad_path.write_bytes(bad)
        templates = {name: assets['assets/templates/' + name] for name in HELPERS}
        source = HERE / 'source'
        flags = ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fno-lto', '-I', source,
                 '-include', source / 'stage_policy.h', '-DMER_PROFILE_WRITE=1',
                 '-DMER_WRITE_REVIEW_BUILD=1', '-DMER_CORE_EXECUTE=1']
        files = [HERE / 'tests/c/test_core.c', source / 'writer_core.c', source / 'sha256.c']
        memory_template = temporary / 'memory-core-template.mipsel'
        run('compile-memory-core-mips', [cc, *flags, '-static', '-mips32r2', '-msoft-float',
                                         '-fno-pie', '-no-pie', '-Wl,--build-id=none', '-o',
                                         memory_template, *files, source / 'policy.c'])
        for identity in ('a', 'b'):
            # No real MAC, calibration bytes, SSH key or backup is part of a
            # public CI test. Two synthetic chips differ in protected regions.
            backup = bytearray(bytes(range(256)) * 65536)
            if identity == 'b':
                for offset in (2, 0xd30020, 0xd40020, 0xd50020, 0xff0020):
                    backup[offset] ^= 0x47
            backup = bytes(backup)
            hashes = {'image': sha(image), 'backup': sha(backup),
                      'stock': sha(backup[0x40000:0xd30000])}
            for _, (name, start, end) in PROTECTED.items():
                hashes[name] = sha(backup[start:end])
            nonces = {'preflight': ('1' if identity == 'a' else '3') * 32,
                      'write': ('2' if identity == 'a' else '4') * 32}
            base = encode_policy(hashes, nonces)
            bound = {name: bind_one(templates[name], base) for name in HELPERS[:2]}
            parent = encode_policy(hashes, nonces, bound)
            bound.update({name: bind_one(templates[name], parent) for name in HELPERS[2:]})
            for name, data in bound.items():
                executable = temporary / (identity + '-' + name)
                executable.write_bytes(data)
                executable.chmod(0o500)
                if name in HELPERS[:2]:
                    argv = ['--check-image', image_path] if name == HELPERS[0] else [
                        '--offline-image-only', '--image', image_path]
                    run(identity + '-' + name + '-image', [qemu, '-cpu', '24KEc', executable, *argv])
                    argv[-1] = bad_path
                    run(identity + '-' + name + '-reject-corrupt-image',
                        [qemu, '-cpu', '24KEc', executable, *argv], expected=1)
                else:
                    info = run(identity + '-' + name + '-bound-policy',
                               [qemu, '-cpu', '24KEc', executable, '--build-info'])
                    nonce = nonces['preflight' if name == HELPERS[2] else 'write']
                    if nonce not in info.stdout or hashes['image'] not in info.stdout:
                        raise RuntimeError('Runtime did not load this device policy')
                    rejection = run(identity + '-' + name + '-non-pid1-rejected',
                                    [qemu, '-cpu', '24KEc', '-strace', executable,
                                     '--execute-fixed-write'], expected=78)
                    if any(v in rejection.stderr for v in ('mount(', 'pivot_root(', 'ioctl(',
                                                           'pwrite64(', 'socket(')):
                        raise RuntimeError('Rejected helper attempted a device operation')
            backup_path = temporary / (identity + '-fake-flash.bin')
            backup_path.write_bytes(backup)
            memory = temporary / (identity + '-memory-core.mipsel')
            memory.write_bytes(bind_one(memory_template.read_bytes(), base))
            memory.chmod(0o500)
            run(identity + '-memory-NOR-207-blocks',
                [qemu, '-cpu', '24KEc', memory, backup_path, image_path, '--nominal-only'])
            # The same production core runs its complete failure matrix under
            # host sanitizers. Only memory callbacks are linked in this test.
            policy = temporary / (identity + '-host-policy.c')
            strings = {
                'image_sha': hashes['image'], 'backup_sha': hashes['backup'], 'stock_sha': hashes['stock'],
                'boot_sha': hashes['boot'], 'device_info_sha': hashes['deviceinfo'],
                'firmware_info_sha': hashes['firmwareinfo'], 'tddp_sha': hashes['tddp'], 'art_sha': hashes['art'],
                'preflight_nonce': nonces['preflight'], 'write_nonce': nonces['write'],
                'preflight_sha': sha(bound[HELPERS[0]]), 'snapshot_helper_sha': sha(bound[HELPERS[1]]),
            }
            initialization = [f'.{name}="{value}"' for name, value in strings.items()]
            initialization += ['.magic=MER_POLICY_MAGIC', '.version=1', '.policy_bytes=748',
                               f'.preflight_bytes={len(bound[HELPERS[0]])}',
                               f'.snapshot_helper_bytes={len(bound[HELPERS[1]])}']
            policy.write_text('#include "install_policy.h"\nconst struct mer_install_policy_data '
                              'mer_install_policy={' + ','.join(initialization) + '};\n', encoding='ascii')
            sanitized = temporary / (identity + '-memory-core.sanitized')
            run(identity + '-compile-sanitized-core', [host_cc, *flags, '-O1', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-o', sanitized, *files, policy])
            run(identity + '-memory-NOR-fault-matrix-ASan-UBSan', [sanitized, backup_path, image_path])
        # Unbound templates cannot even open an image; CI must not publish an
        # installer that accidentally accepts an unbound policy.
        for name in HELPERS[:2]:
            executable = temporary / ('unbound-' + name)
            executable.write_bytes(templates[name])
            executable.chmod(0o500)
            argv = ['--check-image', image_path] if name == HELPERS[0] else [
                '--offline-image-only', '--image', image_path]
            result = run(name + '-unbound-rejected',
                         [qemu, '-cpu', '24KEc', '-strace', executable, *argv], expected=1)
            if 'REJECT' not in result.stderr:
                raise RuntimeError('Unbound rejection was not a policy rejection')
            if any(v in result.stderr for v in ('open(', 'openat(', 'ioctl(', 'mount(',
                                                'pivot_root(', 'pwrite64(', 'socket(')):
                raise RuntimeError('Unbound helper attempted an image or device operation')
    return {'passed': True, 'router_accessed': False, 'device_backend_linked_in_memory_tests': False,
            'hardware_tested': False, 'checks': records, 'image': package['image']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--cc', required=True)
    parser.add_argument('--qemu', default='qemu-mipsel')
    parser.add_argument('--host-cc', default='gcc')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.package, args.cc, args.qemu, args.host_cc)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('OFFLINE_INSTALLER_PASS: synthetic identities, MIPS policies and memory NOR only; hardware_tested=false')
