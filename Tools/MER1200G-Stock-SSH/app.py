# SPDX-License-Identifier: MIT
"""Single-file computer-side SSH installer; default is local verification only."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from policy_binding import HELPERS, PROTECTED, bind_one, encode_policy, make_bundle, require_template, sha


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_package(path):
    """Verify the complete public payload before reading any router or PC state."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'Duplicate archive names')
        package = json.loads(archive.read('package.json'))
        require(package.get('format') == 'mer1200g-stock-ssh-zipapp-v1' and
                package.get('private_per_device') is False, 'Unknown installer package')
        supported = package.get('supported_stock_sha256', [])
        require(isinstance(supported, list) and supported and
                all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) for v in supported),
                'Missing stock firmware compatibility policy')
        files = package['files']
        require(set(names) == set(files) | {'package.json'}, 'Unexpected archive entries')
        data = {}
        for name, expected in files.items():
            require(not name.startswith('/') and '\\' not in name and
                    '..' not in name.split('/'), 'Unsafe archive path')
            item = archive.getinfo(name)
            require(item.file_size == expected['bytes'] and 0 <= item.file_size <= 0x1000000,
                    'Unexpected archive size: ' + name)
            content = archive.read(name)
            require(sha(content) == expected['sha256'], 'Package hash differs: ' + name)
            data[name] = content
    image, metadata = data['assets/window.bin'], package['image']
    require(len(image) == 0xcf0000 and sha(image) == metadata['window_sha256'], 'Firmware window identity')
    length = metadata['sysupgrade_bytes']
    prefix = metadata['immutable_prefix_bytes']
    root, overlay = metadata['rootfs_offset'], metadata['overlay_offset']
    require(0 < root < prefix <= overlay < length < len(image) and
            root % 65536 == overlay % 65536 == 0, 'Invalid verified firmware offsets')
    require(sha(image[:length]) == metadata['sysupgrade_sha256'] and
            image[length:] == b'\xff' * (len(image) - length) and
            sha(image[:prefix]) == metadata['immutable_prefix_sha256'], 'Firmware payload differs')
    require(metadata['profile'] == 'native-ci-current' and metadata['blocks'] == 207 and
            metadata['sysupgrade_metadata']['supported_devices'] == ['mercury,mer1200g-v1'],
            'Wrong firmware target')
    for name in HELPERS:
        require_template(data['assets/templates/' + name])
    return package, data


def open_workdir(args, package_path, data):
    work = Path(args.workdir).resolve() if args.workdir else package_path.with_name(package_path.stem + '-work')
    require(not work.is_symlink(), 'Work directory must not be a symbolic link')
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    identity = sha(package_path.read_bytes())
    marker = work / 'installer-sha256.txt'
    if marker.exists():
        require(marker.read_text(encoding='ascii').strip() == identity,
                'This work directory belongs to another installer; use its original file or a new --workdir')
    else:
        with marker.open('x', encoding='ascii') as out:
            out.write(identity + '\n')
    network = work / 'network'
    network.mkdir(mode=0o700, exist_ok=True)
    script = network / 'network.ps1'
    content = data['assets/network.ps1']
    if script.exists():
        require(script.read_bytes() == content, 'Network script in work directory changed')
    else:
        with script.open('xb') as out:
            out.write(content)
    return work


def network_action(action, args, work):
    require(os.name == 'nt', 'Automatic network preparation requires Windows; configure the documented addresses manually')
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               str(work / 'network' / 'network.ps1'), '-Mode', action.capitalize(),
               '-InterfaceAlias', args.interface_alias, '-PythonExecutable', sys.executable]
    if action == 'prepare':
        require(args.direct_lan, 'Connect PC directly to port 5 and unplug WAN, then use --direct-lan')
        command.append('-DirectLan')
    subprocess.run(command, check=True)


def verify_bundle(bundle, package, data):
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    require(manifest.get('image') == package['image'] and manifest.get('target_profile') == 'native-ci-current',
            'Bound bundle belongs to a different firmware')
    require(manifest.get('stock_region_sha256') in package['supported_stock_sha256'],
            'Bound bundle stock firmware is outside this installer compatibility policy')
    require(set(manifest['files']) == set(HELPERS) | {'image.bin'}, 'Incomplete bound bundle')
    actual = {}
    for name, expected in manifest['files'].items():
        content = (bundle / name).read_bytes()
        require(len(content) == expected['bytes'] and sha(content) == expected['sha256'],
                'Bound file changed: ' + name)
        actual[name] = content
    require(actual['image.bin'] == data['assets/window.bin'], 'Bound firmware differs from this package')
    hashes = {'image': sha(actual['image.bin']), 'backup': manifest['backup_sha256'],
              'stock': manifest['stock_region_sha256']}
    for key, (name, _, _) in PROTECTED.items():
        hashes[name] = manifest['protected'][key]
    base = encode_policy(hashes, manifest['nonce'])
    expected_helpers = {name: bind_one(data['assets/templates/' + name], base) for name in HELPERS[:2]}
    parent = encode_policy(hashes, manifest['nonce'], expected_helpers)
    expected_helpers.update({name: bind_one(data['assets/templates/' + name], parent) for name in HELPERS[2:]})
    require(all(actual[name] == expected_helpers[name] for name in HELPERS),
            'Bound helper code or policy differs from this installer')
    return manifest


def controller_action(action, bundle):
    import controller
    previous = sys.argv
    try:
        sys.argv = ['controller', action, '--bundle', str(bundle)]
        controller.main()
    finally:
        sys.argv = previous


def check(args, work, package, data):
    bundle = work / 'bundle'
    if not bundle.exists():
        from bootstrap import collect_stock
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        capture = work / 'captures' / stamp
        stock = collect_stock(capture, args.host, supported_stock_sha256=package['supported_stock_sha256'])
        templates = {name: data['assets/templates/' + name] for name in HELPERS}
        make_bundle(templates, data['assets/window.bin'], package['image'], stock, bundle)
    verify_bundle(bundle, package, data)
    controller_action('inspect', bundle)
    print('STOCK_CHECK_PASS: new-device bundle bound and current stock verified; ready_for_flashing=false', flush=True)


def main():
    require(__debug__, 'Run Python without -O; validation must remain enabled')
    require(sys.version_info >= (3, 10), 'Python 3.10 or newer is required')
    parser = argparse.ArgumentParser(description='MER1200G v1 single-file SSH installer (run on the computer)')
    parser.add_argument('action', nargs='?', default='verify',
                        choices=['verify', 'password', 'prepare', 'check', 'rehearse', 'flash', 'restore', 'install'])
    parser.add_argument('--workdir', '--work-dir')
    parser.add_argument('--host', default='192.168.2.50', choices=['192.168.2.50'])
    parser.add_argument('--interface-alias', default='以太网')
    parser.add_argument('--direct-lan', action='store_true')
    parser.add_argument('--mac', help='Stock LAN MAC used only for local diagnostic-password calculation')
    args = parser.parse_args()
    try:
        if args.action == 'password':
            mac = args.mac if args.mac else input('Stock LAN MAC: ')
            normalized = re.sub(r'[-:.\s]', '', mac).upper()
            require(re.fullmatch(r'[0-9A-F]{12}', normalized), 'Invalid stock LAN MAC')
            print(hashlib.md5(normalized.encode('ascii')).hexdigest()[:8])
            return
        path = Path(sys.argv[0]).resolve()
        package, data = read_package(path)
        print('KIT_VERIFY_PASS: single-file installer and embedded firmware match; no router connection yet', flush=True)
        if args.action == 'verify':
            return
        if args.action in ('check', 'rehearse', 'flash', 'install'):
            import paramiko
            require(paramiko.__version__ == '3.5.1', 'Install paramiko==3.5.1 before using SSH modes')
        work = open_workdir(args, path, data)
        print('Work directory: ' + str(work), flush=True)
        if args.action in ('prepare', 'restore'):
            network_action(args.action, args, work)
        elif args.action == 'check':
            check(args, work, package, data)
        elif args.action in ('rehearse', 'flash'):
            verify_bundle(work / 'bundle', package, data)
            controller_action(args.action, work / 'bundle')
        elif args.action == 'install':
            # All four stages are authorized by this explicit command. The
            # reviewed controller still waits for both physical power cycles.
            # On any failure, keep the network and evidence for diagnosis.
            network_action('prepare', args, work)
            check(args, work, package, data)
            controller_action('rehearse', work / 'bundle')
            verify_bundle(work / 'bundle', package, data)
            controller_action('flash', work / 'bundle')
            network_action('restore', args, work)
            print('INSTALL_COMPLETE: SSH installation verified and computer network restored', flush=True)
    except (Exception, KeyboardInterrupt) as error:
        print('STOP: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr, flush=True)
        print('Keep the current power state and work directory. Do not repeat a RAM activation after an error.',
              file=sys.stderr, flush=True)
        raise SystemExit(1)
