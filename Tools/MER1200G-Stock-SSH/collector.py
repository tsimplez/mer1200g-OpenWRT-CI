# SPDX-License-Identifier: MIT
"""Strict status receiver with receipt ACKs. Never issues device commands."""
import copy
import datetime
import hashlib
import json
import re
import socket
import threading
import time

from network_contract import NETWORK, require_network
from protocol_contract import STATUS_PROTOCOL, FINAL_GRACE_SECONDS, require_protocol


def parse(raw):
    if not 1 <= len(raw) <= 1400:
        raise ValueError('packet size')
    if not raw.endswith(b'\n') or b'\n' in raw[:-1] or b'\r' in raw or b'\x00' in raw:
        raise ValueError('packet framing')
    parts = raw.decode('ascii').split()
    if not parts or parts[0] != 'MER1':
        raise ValueError('marker')
    fields = {}
    for part in parts[1:]:
        key, value = part.split('=', 1)
        if not re.fullmatch('[a-z][a-z0-9_]*', key) or key in fields or not value:
            raise ValueError('field')
        fields[key] = value
    for key in ('seq', 'phase', 'at'):
        value = fields.get(key, '')
        if not re.fullmatch('0|[1-9][0-9]*', value) or int(value) >= 2**32:
            raise ValueError(key)
    if fields['seq'] == '0':
        raise ValueError('seq')
    code = fields.get('code', '')
    if not re.fullmatch('0|-?[1-9][0-9]*', code) or not -(2**31) <= int(code) < 2**31:
        raise ValueError('code')
    if not re.fullmatch('[0-9a-f]{8}', fields.get('checks', '')):
        raise ValueError('checks')
    return fields


def final_errors(packet, manifest, mode):
    writing = mode == 'write'
    image = manifest['files']['image.bin']['sha256']
    boot = manifest['protected']['MER_BOOT_SHA']
    exact = {'proto': STATUS_PROTOCOL, 'nonce': manifest['nonce'][mode], 'image': image,
             'profile': 'stock-ssh-' + mode + '-v2', 'phase': '50', 'at': '50',
             'code': '0', 'checks': '001fffff' if writing else '0000ffff',
             'preflight': '1', 'snapshot': '1', 'jffs': '1', 'alloc': '30408704'}
    if writing:
        exact.update({'pending_mut': '0', 'pending_close': '0', 'erase_ok': '207',
                      'block_ok': '207', 'program_bytes': '13565952', 'core_error': '0',
                      'guard_error': '0', 'target_error': '0', 'close_error': '0',
                      'target_valid': '1', 'target_equal': '1', 'guard_valid': '1',
                      'closed': '1', 'base_boot': boot, 'after_boot': boot,
                      'base_desired': image, 'readback': image})
    else:
        exact.update({'boot': boot, 'desired': image})
    errors = [key for key, value in exact.items() if packet.get(key) != value]
    if writing:
        for before, after in [('base_rest', 'after_rest'), ('base_metadata', 'after_metadata')]:
            if not re.fullmatch('[0-9a-f]{64}', packet.get(before, '')) or packet.get(before) != packet.get(after):
                errors.append(after)
        if not packet.get('programs', '').isdigit() or int(packet['programs']) < 52992:
            errors.append('programs')
    else:
        for key in ['rest', 'metadata']:
            if not re.fullmatch('[0-9a-f]{64}', packet.get(key, '')):
                errors.append(key)
    return errors


def acknowledgement(raw, packet):
    return ('MERACK1 nonce=' + packet['nonce'] + ' image=' + packet['image'] +
            ' profile=' + packet['profile'] + ' seq=' + packet['seq'] +
            ' payload_sha256=' + hashlib.sha256(raw).hexdigest() + '\n').encode('ascii')


class FinalObservation:
    """A clean grace interval permits an explicit end, never automatic exit."""
    def __init__(self, grace_seconds=FINAL_GRACE_SECONDS, clock=time.monotonic):
        if grace_seconds < FINAL_GRACE_SECONDS:
            raise ValueError('Final grace cannot be shorter than the protocol contract')
        self.grace_seconds, self.clock = grace_seconds, clock
        self.provisional_since = None
        self.ready = False

    def update(self, snapshot):
        clean = (snapshot.get('complete') and not snapshot.get('failure_latched') and
                 snapshot.get('gaps') == 0 and snapshot.get('conflicts', 0) == 0 and
                 snapshot.get('ack_failures', 0) == 0)
        if not clean:
            self.provisional_since = None
            self.ready = False
        else:
            now = self.clock()
            if self.provisional_since is None:
                self.provisional_since = now
            # Time alone is insufficient: another distinct FINAL must confirm
            # the receiver stayed active through the full grace boundary.
            self.ready = (now - self.provisional_since >= self.grace_seconds and
                          snapshot.get('last_new_final_at', -1) >=
                          self.provisional_since + self.grace_seconds)
        return {'provisional': self.provisional_since is not None,
                'ready_for_power_cycle': self.ready,
                'grace_seconds': self.grace_seconds,
                'receiver_must_remain_active': True}

    def require_explicit_end(self, snapshot):
        state = self.update(snapshot)
        if not state['ready_for_power_cycle']:
            raise RuntimeError('Observation ended before a clean final grace interval; not accepted')
        return state


class Collector:
    def __init__(self, manifest, mode, output, *, sock=None, clock=time.monotonic):
        require_network(manifest)
        require_protocol(manifest)
        if mode not in ('preflight', 'write'):
            raise ValueError('Unknown status profile')
        self.manifest, self.mode, self.output, self.clock = manifest, mode, output, clock
        self.state = {'packets': 0, 'received_bytes': 0, 'accepted': 0, 'accepted_bytes': 0,
                      'duplicates': 0, 'rejected': 0, 'acks_sent': 0, 'ack_bytes': 0,
                      'ack_failures': 0, 'last_seq': 0, 'last_observed_seq': 0,
                      'gaps': 0, 'reordered': 0, 'conflicts': 0, 'finals': 0,
                      'complete': False, 'failure_latched': False}
        self.lock = threading.Lock()
        self.error = None
        self.sender = None
        self.history = {}
        self._log = None
        self.sock = sock if sock is not None else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if sock is None:
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
                self.sock.bind((NETWORK['pc_ipv4'], NETWORK['udp_port']))
                self.sock.settimeout(.2)
            except BaseException:
                self.sock.close()
                raise

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def _record(self, raw, peer, outcome, detail=''):
        if self._log is not None:
            record = {'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      'peer': list(peer), 'outcome': outcome, 'bytes': len(raw),
                      'raw': raw.decode('ascii', 'backslashreplace')}
            if detail:
                record['detail'] = detail
            self._log.write(json.dumps(record, separators=(',', ':')) + '\n')

    def _fail(self, reason):
        self.state['failure_latched'] = True
        self.state['complete'] = False
        self.state['finals'] = 0
        self.state.setdefault('failure_reason', reason)

    def _ack(self, raw, packet, peer):
        ack = acknowledgement(raw, packet)
        try:
            if self.sock.sendto(ack, peer) != len(ack):
                raise OSError('Short UDP ACK send')
        except OSError as error:
            self.state['ack_failures'] += 1
            self._fail('ACK send failed')
            self.error = 'ACK send failed: ' + str(error)
            self._record(raw, peer, 'ack-failed', str(error))
            return False
        self.state['acks_sent'] += 1
        self.state['ack_bytes'] += len(ack)
        return True

    def accept(self, raw, peer):
        with self.lock:
            try:
                return self._accept(raw, peer)
            except BaseException as error:
                self.error = str(error)
                self._fail('Receiver failed while recording a packet')
                raise

    def expected_identity(self):
        return {'proto': STATUS_PROTOCOL, 'nonce': self.manifest['nonce'][self.mode],
                'image': self.manifest['files']['image.bin']['sha256'],
                'profile': 'stock-ssh-' + self.mode + '-v2'}

    def final_packet_errors(self, packet):
        return final_errors(packet, self.manifest, self.mode)

    def parse_packet(self, raw):
        return parse(raw)

    def _accept(self, raw, peer):
        self.state['packets'] += 1
        self.state['received_bytes'] += len(raw)
        if (not isinstance(peer, tuple) or len(peer) != 2 or
                peer[0] != NETWORK['router_ipv4'] or not isinstance(peer[1], int) or
                not 1 <= peer[1] <= 65535):
            self.state['rejected'] += 1
            self._record(raw, peer if isinstance(peer, tuple) else (str(peer), 0), 'foreign-peer')
            return False
        if self.sender is not None and peer != self.sender:
            self.state['rejected'] += 1
            self._record(raw, peer, 'changed-sender')
            self._fail('Sender tuple changed')
            return False
        try:
            packet = self.parse_packet(raw)
            seq = int(packet['seq'])
        except (ValueError, UnicodeError, KeyError) as error:
            self.state['rejected'] += 1
            self._record(raw, peer, 'malformed', str(error))
            if self.sender == peer:
                self._fail('Malformed packet from established sender')
            return False
        identity = self.expected_identity()
        if any(packet.get(key) != value for key, value in identity.items()):
            self.state['rejected'] += 1
            self._record(raw, peer, 'wrong-identity')
            if self.sender == peer:
                self._fail('Identity changed within established sender')
            return False
        self.state['last_observed_seq'] = max(seq, self.state['last_observed_seq'])
        if self.state['failure_latched']:
            self.state['rejected'] += 1
            self._record(raw, peer, 'failure-already-latched')
            return False
        if seq <= self.state['last_seq']:
            if self.history.get(seq) != raw:
                self.state['rejected'] += 1
                self.state['conflicts'] += 1
                self.state['reordered'] += 1
                self._record(raw, peer, 'conflicting-duplicate')
                self._fail('Different bytes for an accepted sequence')
                return False
            self.state['duplicates'] += 1
            if not self._ack(raw, packet, peer):
                return False
            self._record(raw, peer, 'exact-duplicate-reacked')
            return True
        if seq != self.state['last_seq'] + 1:
            self.state['gaps'] += seq - self.state['last_seq'] - 1
            self.state['rejected'] += 1
            self._record(raw, peer, 'sequence-gap')
            self._fail('Unobserved sequence prefix')
            return False
        invalid_final = packet['phase'] == '50' and self.final_packet_errors(packet)
        if packet['code'] != '0' or invalid_final:
            self.state['rejected'] += 1
            self.state['latest'] = packet
            self._record(raw, peer, 'reported-failure' if packet['code'] != '0' else 'invalid-final',
                         ','.join(invalid_final) if invalid_final else '')
            self._fail('Device error or invalid FINAL')
            return False
        if self.sender is None:
            self.sender = peer
            self.state['sender'] = list(peer)
        # No accepted prefix / FINAL state is visible until ACK send succeeds.
        if not self._ack(raw, packet, peer):
            return False
        self.history[seq] = bytes(raw)
        self.state['last_seq'] = seq
        self.state['accepted'] += 1
        self.state['accepted_bytes'] += len(raw)
        self.state['latest'] = packet
        self.state['last_ack_at'] = self.clock()
        if packet.get('phase') == '50':
            self.state['finals'] += 1
            self.state['last_new_final_at'] = self.clock()
        else:
            self.state['finals'] = 0
        self._record(raw, peer, 'accepted-new')
        self.state['complete'] = self.state['finals'] >= 3
        if self.state['complete'] and self._log is not None:
            self._log.flush()
        return True

    def run(self, stop):
        try:
            with (self.output / 'packets.jsonl').open('x', encoding='utf8', buffering=1024 * 1024) as log:
                self._log = log
                flushed = time.monotonic()
                while not stop.is_set():
                    try:
                        raw, peer = self.sock.recvfrom(2048)
                    except socket.timeout:
                        raw = None
                    if raw is not None:
                        self.accept(raw, peer)
                        if self.error:
                            raise RuntimeError(self.error)
                    if time.monotonic() - flushed >= 1:
                        log.flush()
                        (self.output / 'progress.json').write_text(json.dumps(self.snapshot(), indent=2))
                        flushed = time.monotonic()
        except BaseException as error:
            self.error = str(error)
            with self.lock:
                self._fail('Receiver stopped with an error')
        finally:
            self._log = None
            try:
                self.sock.close()
            except BaseException as error:
                self.error = self.error or 'Receiver socket close failed: ' + str(error)
                with self.lock:
                    self._fail('Receiver socket close failed')
            try:
                (self.output / 'progress.json').write_text(json.dumps(self.snapshot(), indent=2))
            except BaseException as error:
                self.error = self.error or 'Final progress record failed: ' + str(error)
                with self.lock:
                    self._fail('Final progress record failed')
