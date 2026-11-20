"""Read-only checks over a fresh SSH connection after the operator power-cycles."""
import hashlib
import json
import re

def native_layout(image):
    root = image['rootfs_offset']
    overlay = image['overlay_offset']
    require(0 < root < overlay < 0xcf0000 and root % 65536 == overlay % 65536 == 0,
            'Invalid verified native image offsets')
    return [
    (0x40000, 'bootloader'), (0xcf0000, 'firmware'),
    (root, 'kernel'), (0xcf0000-root, 'rootfs'), (0xcf0000-overlay, 'rootfs_data'),
    (0x10000, 'device-info'), (0x10000, 'firmware-info'), (0x10000, 'tddp'),
    (0x20000, 'log'), (0x70000, 'reserved'),
    (0x200000, 'rootfs-data-stock'), (0x10000, 'art'),
    ]
BOOT_ID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_reboot(client, manifest, before, *, command, inspect_stock):
    """Accept only a new authenticated boot of the expected system and device."""
    transport = client.get_transport()
    require(transport is not None and transport.is_authenticated(), 'SSH is not authenticated')
    host_key = sha(transport.get_remote_server_key().asbytes())
    boot = command(client, 'cat /proc/sys/kernel/random/boot_id').decode().strip()
    require(re.fullmatch(BOOT_ID, boot) is not None, 'Invalid boot ID')
    require(boot != before['inspection']['boot_id'], 'Router is still on the previous boot')
    evidence = {'method': 'authenticated-ssh', 'action': before['action'],
                'manifest_sha256': before['manifest_sha256'],
                'previous_boot_id': before['inspection']['boot_id'], 'boot_id': boot,
                'host_key_sha256': host_key, 'ssh_authenticated': True}
    if before['action'] == 'rehearse':
        require(host_key == before['host_key_sha256'], 'Stock SSH host key changed after rehearsal')
        checked = inspect_stock(client, manifest)
        require(checked['boot_id'] == boot and checked['stock_and_protected_ranges_match'] is True,
                'Stock inspection failed after rehearsal')
        evidence.update(system='stock', kernel=checked['kernel'],
                        stock_and_protected_ranges_match=True)
    elif before['action'] == 'flash':
        board = json.loads(command(client, 'ubus call system board'))
        require(board.get('board_name') == 'mercury,mer1200g-v1', 'Wrong native board')
        require(board.get('kernel') == manifest['image']['kernel_release'], 'Wrong native kernel')
        require(board.get('rootfs_type') == 'squashfs', 'Not the persistent SquashFS image')
        require(board.get('release', {}).get('revision') ==
                manifest['image']['sysupgrade_metadata']['version']['revision'], 'Wrong firmware revision')
        text = command(client, 'cat /proc/mtd').decode()
        expected_layout = native_layout(manifest['image'])
        rows = re.findall(r'^mtd(\d+): ([0-9a-f]+) ([0-9a-f]+) "([^"]+)"$', text, re.M)
        require(len(rows) == len(expected_layout), 'Wrong native MTD count')
        for number, (index, size, erase, name) in enumerate(rows):
            require(int(index) == number and int(erase, 16) == 65536 and
                    (int(size, 16), name) == expected_layout[number], 'Wrong native MTD layout')
        mounts = [line.split() for line in command(client, 'cat /proc/mounts').decode().splitlines()]
        require(any(len(m) >= 4 and m[0] == '/dev/root' and m[1:3] == ['/rom', 'squashfs']
                    and 'ro' in m[3].split(',') for m in mounts), 'Flash /rom is not mounted')
        require(any(len(m) >= 4 and m[0] == '/dev/mtdblock4' and m[1:3] == ['/overlay', 'jffs2']
                    and 'rw' in m[3].split(',') for m in mounts), 'Flash overlay is not mounted')
        # Read a fixed count, then compare only the immutable kernel/SquashFS prefix.
        # The running overlay is expected to have changed on first boot.
        prefix_bytes = manifest['image']['immutable_prefix_bytes']
        count = (prefix_bytes + 65535) // 65536
        raw = command(client, 'dd if=/dev/mtd1 bs=65536 count=' + str(count), 180)
        require(len(raw) == count * 65536, 'Short flash read')
        prefix_sha = sha(raw[:prefix_bytes])
        require(prefix_sha == manifest['image']['immutable_prefix_sha256'], 'Running flash image differs')
        for index, size, key in [(0, 0x40000, 'MER_BOOT_SHA'), (5, 0x10000, 'MER_DEVICE_INFO_SHA'),
                                 (6, 0x10000, 'MER_FIRMWARE_INFO_SHA'), (7, 0x10000, 'MER_TDDP_SHA'),
                                 (11, 0x10000, 'MER_ART_SHA')]:
            raw = command(client, 'cat /dev/mtd' + str(index))
            require(len(raw) == size and sha(raw) == manifest['protected'][key],
                    'Protected identity differs after boot: ' + key)
        evidence.update(system='native', kernel=board['kernel'], board_name=board['board_name'],
                        flash_mounts_verified=True, native_layout_verified=True,
                        immutable_prefix_sha256=prefix_sha, protected_ranges_match=True)
    else:
        raise RuntimeError('Reboot verification only applies to rehearse/flash')
    require(command(client, 'cat /proc/sys/kernel/random/boot_id').decode().strip() == boot,
            'Boot changed during verification')
    return evidence


def require_rehearsal(rehearsal, current):
    """The flash operation must follow this bundle's verified stock reboot."""
    require(rehearsal.get('action') == 'rehearse' and rehearsal.get('completed') is True,
            'Successful native-installer rehearsal required')
    require(rehearsal.get('manifest_sha256') == current['manifest_sha256'] and
            rehearsal.get('host_key_sha256') == current['host_key_sha256'], 'Rehearsal identity differs')
    proof = rehearsal.get('reboot_verification', {})
    require(proof.get('method') == 'authenticated-ssh' and proof.get('ssh_authenticated') is True and
            proof.get('system') == 'stock' and proof.get('stock_and_protected_ranges_match') is True,
            'Missing authenticated stock reboot verification')
    require(proof.get('manifest_sha256') == current['manifest_sha256'] and
            proof.get('action') == 'rehearse' and proof.get('host_key_sha256') == current['host_key_sha256'],
            'Reboot verification is for another run or device')
    require(proof.get('previous_boot_id') == rehearsal['inspection']['boot_id'] and
            proof.get('boot_id') == current['inspection']['boot_id'] and
            proof['boot_id'] != proof['previous_boot_id'], 'Run rehearsal again on this stock boot')
