#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build one public SSH installer zipapp using the CI firmware and toolchain."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from image_format import make_window
from policy_binding import HELPERS, require_template

HERE = Path(__file__).resolve().parent
MODULES = ('app.py', 'bootstrap.py', 'controller.py', 'collector.py', 'network_contract.py',
           'protocol_contract.py', 'reboot_check.py', 'policy_binding.py')


def build(sysupgrade, cc, output):
    image, metadata = make_window(Path(sysupgrade).read_bytes())
    metadata['window_sha256'] = hashlib.sha256(image).hexdigest()
    supported = json.loads((HERE / 'supported_stock.json').read_text(encoding='utf-8'))
    if supported.get('format') != 'mer1200g-stock-compatibility-v1':
        raise ValueError('Unknown stock compatibility policy')
    with tempfile.TemporaryDirectory(prefix='mer1200g-installer-') as temp:
        temp = Path(temp)
        source = HERE / 'source'
        flags = ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-static', '-mips32r2',
                 '-msoft-float', '-fno-pie', '-no-pie', '-fno-lto', '-Wl,--build-id=none', '-I', str(source)]
        common = ['enabled_entry.c', 'handover_ops.c', 'mount_graph.c', 'status.c', 'status_transport.c',
                  'sha256.c', 'live_guard.c', 'cleanup_jffs2.c', 'snapshot_report.c', 'capture_readonly.c']
        stage_flags = ['-include', str(source / 'stage_policy.h'),
                       '-DMER_BUILD_RAM_PREFLIGHT_STAGE=1', '-DMER_REVIEW_REAL_OPS=1']
        specs = {
            HELPERS[0]: (['stock_preflight.c', 'sha256.c'], []),
            HELPERS[1]: (['snapshot_helper.c', 'writer_core.c', 'sha256.c'], []),
            HELPERS[2]: (common, stage_flags),
            HELPERS[3]: (common + ['writer_core.c', 'writer_flow.c', 'writer_runtime.c', 'traced_io.c',
                                  'writer_ledger.c'], stage_flags + ['-DMER_PROFILE_WRITE=1',
                                  '-DMER_WRITE_REVIEW_BUILD=1', '-DMER_CORE_EXECUTE=1']),
        }
        assets = {'assets/window.bin': image}
        for name, (files, extra) in specs.items():
            executable = temp / name
            subprocess.run([cc, *flags, *extra, '-o', str(executable),
                            *[str(source / f) for f in files], str(source / 'policy.c')], check=True)
            data = executable.read_bytes()
            require_template(data)
            assets['assets/templates/' + name] = data
        for name in MODULES:
            assets[name] = (HERE / name).read_bytes()
        assets['assets/network.ps1'] = (HERE / 'network.ps1').read_bytes()
        assets['__main__.py'] = b'from app import main\nmain()\n'
        assets['README.md'] = (HERE / 'README.md').read_bytes()
        assets['LICENSE'] = (HERE.parent.parent / 'LICENSE').read_bytes()
        package = {
            'format': 'mer1200g-stock-ssh-zipapp-v1', 'private_per_device': False,
            'hardware_tested': False, 'image': metadata,
            'supported_stock_sha256': supported['stock_region_sha256'],
            'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                      for name, data in assets.items()},
        }
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise FileExistsError('Use a new installer output path: ' + str(output))
        stage = output.with_name(output.name + '.building')
        with stage.open('xb') as stream:
            stream.write(b'#!/usr/bin/env python3\n')
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for name, data in sorted(assets.items()):
                    archive.writestr(name, data)
                archive.writestr('package.json', json.dumps(package, indent=2) + '\n')
        os.replace(stage, output)
        print(json.dumps({'output': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                          'image': metadata, 'router_accessed': False, 'hardware_tested': False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sysupgrade', required=True, type=Path)
    parser.add_argument('--cc', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    build(args.sysupgrade, args.cc, args.output)
