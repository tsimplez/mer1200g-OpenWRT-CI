# SPDX-License-Identifier: MIT
"""Exercise the binding boundary with small, non-runnable synthetic MIPS ELFs."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy_binding import (HELPERS, MAGIC, POLICY_BYTES, PROTECTED, SHA_NAMES,
                            bind_one, encode_policy, make_bundle, policy_span,
                            require_template, sha)


POLICY_OFFSET = 0x200
POLICY_ADDRESS = 0x410200
SECTION_TABLE = 0x600


def template_elf(*, duplicate_policy=False, policy_flags=2, load_flags=4,
                 memory_size=0x318, load_type=1, policy_address=POLICY_ADDRESS,
                 elf_flags=0x70001001, fp_abi=3, schema_version=1,
                 schema_bytes=POLICY_BYTES, entry=0x400100,
                 code_memory_bytes=16, abi_program_type=0x70000003):
    """Construct headers/segments and a policy slot, never executable machine code."""
    names = b'\0.mer_policy\0.shstrtab\0.MIPS.abiflags\0.text\0'
    name_offsets = {name: names.index(name.encode('ascii') + b'\0')
                    for name in ('.mer_policy', '.shstrtab', '.MIPS.abiflags', '.text')}
    policy = struct.pack('<16sIIII', MAGIC, schema_version, schema_bytes, 0, 0)
    policy += (b'?' * 64 + b'\0') * 8
    policy += (b'?' * 32 + b'\0') * 2
    policy += (b'?' * 64 + b'\0') * 2
    assert len(policy) == POLICY_BYTES
    sections = [
        (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        (name_offsets['.text'], 1, 6, 0x400100, 0x100, 16, 0, 0, 16, 0),
        (name_offsets['.mer_policy'], 1, policy_flags, policy_address,
         POLICY_OFFSET, POLICY_BYTES, 0, 0, 4, 0),
        (name_offsets['.MIPS.abiflags'], 0x7000002A, 2, 0x410500,
         0x500, 24, 0, 0, 8, 0),
        (name_offsets['.shstrtab'], 3, 0, 0, 0x540, len(names), 0, 0, 1, 0),
    ]
    if duplicate_policy:
        sections.append(sections[2])
    elf = bytearray(SECTION_TABLE + len(sections) * 40)
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    header = (ident, 2, 8, 1, entry, 52, SECTION_TABLE, elf_flags,
              52, 32, 3, 40, len(sections), 4)
    struct.pack_into('<16sHHIIIIIHHHHHH', elf, 0, *header)
    programs = [
        (1, 0x100, 0x400100, 0x400100, 16, code_memory_bytes, 5, 0x1000),
        (load_type, POLICY_OFFSET, POLICY_ADDRESS, POLICY_ADDRESS,
         0x318, memory_size, load_flags, 0x1000),
        (abi_program_type, 0x500, 0x410500, 0x410500, 24, 24, 4, 8),
    ]
    for index, program in enumerate(programs):
        struct.pack_into('<8I', elf, 52 + 32 * index, *program)
    elf[POLICY_OFFSET:POLICY_OFFSET + POLICY_BYTES] = policy
    struct.pack_into('<HBBBBBBIIII', elf, 0x500,
                     0, 32, 2, 1, 0, 0, fp_abi, 0, 0, 0, 0)
    elf[0x540:0x540 + len(names)] = names
    for index, section in enumerate(sections):
        struct.pack_into('<10I', elf, SECTION_TABLE + 40 * index, *section)
    return bytes(elf)


def example_bindings():
    return ({name: sha(name.encode('ascii')) for name in SHA_NAMES},
            {'preflight': '1' * 32, 'write': '2' * 32})


class PolicySectionTests(unittest.TestCase):
    def test_legal_template_has_one_fixed_span(self):
        self.assertEqual(require_template(template_elf()), (POLICY_OFFSET, POLICY_BYTES))

    def test_binding_changes_only_the_policy_data(self):
        original = template_elf()
        hashes, nonces = example_bindings()
        policy = encode_policy(hashes, nonces)
        bound = bind_one(original, policy)
        self.assertEqual(len(bound), len(original))
        self.assertEqual(bound[:POLICY_OFFSET], original[:POLICY_OFFSET])
        self.assertEqual(bound[POLICY_OFFSET + POLICY_BYTES:],
                         original[POLICY_OFFSET + POLICY_BYTES:])
        self.assertEqual(bound[POLICY_OFFSET:POLICY_OFFSET + POLICY_BYTES], policy)
        self.assertEqual(policy_span(bound), (POLICY_OFFSET, POLICY_BYTES))

    def test_bound_template_cannot_be_rebound(self):
        hashes, nonces = example_bindings()
        policy = encode_policy(hashes, nonces)
        bound = bind_one(template_elf(), policy)
        with self.assertRaisesRegex(ValueError, 'already bound'):
            bind_one(bound, policy)
        with self.assertRaisesRegex(ValueError, 'already bound'):
            require_template(bound)

    def test_duplicate_section_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Exactly one policy'):
            policy_span(template_elf(duplicate_policy=True))

    def test_writable_or_executable_policy_section_rejected(self):
        for flags in (3, 6):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, 'readonly allocated'):
                policy_span(template_elf(policy_flags=flags))

    def test_policy_requires_readonly_readable_load(self):
        for flags in (6, 0, 1):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, 'readonly loaded'):
                policy_span(template_elf(load_flags=flags))

    def test_policy_cannot_live_only_in_an_unloaded_segment(self):
        with self.assertRaisesRegex(ValueError, 'readonly loaded'):
            policy_span(template_elf(load_type=0))

    def test_policy_virtual_mapping_must_match_file_mapping(self):
        with self.assertRaisesRegex(ValueError, 'readonly loaded'):
            policy_span(template_elf(policy_address=POLICY_ADDRESS + 4))

    def test_load_file_bytes_must_fit_memory(self):
        with self.assertRaisesRegex(ValueError, 'segment bounds'):
            policy_span(template_elf(memory_size=POLICY_BYTES - 1))

    def test_load_cannot_claim_bytes_past_file(self):
        elf = bytearray(template_elf())
        struct.pack_into('<I', elf, 52 + 32 + 16, len(elf) + 1)
        struct.pack_into('<I', elf, 52 + 32 + 20, len(elf) + 1)
        with self.assertRaisesRegex(ValueError, 'segment bounds'):
            policy_span(bytes(elf))

    def test_entry_requires_an_executable_segment(self):
        with self.assertRaisesRegex(ValueError, 'Entry point'):
            policy_span(template_elf(entry=POLICY_ADDRESS))

    def test_entry_in_zero_filled_bss_is_not_executable_code(self):
        with self.assertRaisesRegex(ValueError, 'Entry point'):
            policy_span(template_elf(entry=0x400111, code_memory_bytes=32))

    def test_static_musl_cpic_marker_is_accepted(self):
        self.assertEqual(require_template(template_elf(elf_flags=0x70001005)),
                         (POLICY_OFFSET, POLICY_BYTES))

    def test_wrong_architecture_or_abi_rejected(self):
        for flags in (0x50001001, 0x70000001, 0x70001021):
            with self.subTest(flags=hex(flags)), self.assertRaisesRegex(ValueError, 'MIPS32r2 O32'):
                policy_span(template_elf(elf_flags=flags))

    def test_hard_float_abi_rejected(self):
        with self.assertRaisesRegex(ValueError, 'soft-float'):
            policy_span(template_elf(fp_abi=1))

    def test_abi_section_requires_corresponding_runtime_program(self):
        with self.assertRaisesRegex(ValueError, 'ABI'):
            policy_span(template_elf(abi_program_type=0))

    def test_dynamic_or_interpreted_helper_rejected(self):
        for segment_type in (2, 3):
            with self.subTest(segment_type=segment_type), self.assertRaisesRegex(ValueError, 'statically linked'):
                policy_span(template_elf(abi_program_type=segment_type))

    def test_wrong_schema_version_or_length_rejected(self):
        for kwargs in ({'schema_version': 2}, {'schema_bytes': POLICY_BYTES - 1}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'Unknown policy schema'):
                policy_span(template_elf(**kwargs))

    def test_wrong_serialized_binding_size_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Wrong binding size'):
            bind_one(template_elf(), bytes(POLICY_BYTES - 1))

    def test_sha_and_nonce_fields_require_exact_lowercase_hex(self):
        hashes, nonces = example_bindings()
        for bad in ('a' * 63, 'A' * 64, '?' * 64):
            with self.subTest(hash=bad[:8]), self.assertRaisesRegex(ValueError, 'Invalid policy hash'):
                encode_policy({**hashes, 'art': bad}, nonces)
        for bad in ('1' * 31, 'G' * 32, '1' * 31 + '\0'):
            with self.subTest(nonce=bad[:8]), self.assertRaisesRegex(ValueError, 'Invalid nonce'):
                encode_policy(hashes, {**nonces, 'write': bad})

    def test_child_policy_has_no_self_hash_dependency(self):
        hashes, nonces = example_bindings()
        child_policy = encode_policy(hashes, nonces)
        self.assertEqual(child_policy[24:32], bytes(8))
        self.assertEqual(child_policy[618:], (b'?' * 64 + b'\0') * 2)
        children = {name: bind_one(template_elf(), child_policy) for name in HELPERS[:2]}
        parent_policy = encode_policy(hashes, nonces, children)
        self.assertEqual(struct.unpack_from('<II', parent_policy, 24),
                         tuple(len(children[name]) for name in HELPERS[:2]))
        self.assertEqual(parent_policy[618:683], sha(children[HELPERS[0]]).encode('ascii') + b'\0')
        self.assertEqual(parent_policy[683:], sha(children[HELPERS[1]]).encode('ascii') + b'\0')

    def test_bundle_records_bound_child_hashes_and_fresh_nonces(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture = root / 'capture'
            capture.mkdir()
            backup = bytes(range(256)) * 65536
            path = capture / 'full-flash.bin'
            path.write_bytes(backup)
            (capture / 'known_hosts').write_text('synthetic-host-key\n', encoding='ascii')
            stock = {
                'backup_path': str(path), 'backup_sha256': sha(backup),
                'stock_region_sha256': sha(backup[0x40000:0xd30000]),
                'stock_host_fingerprint': 'a' * 43,
                'protected': {key: sha(backup[start:end])
                              for key, (_, start, end) in PROTECTED.items()},
            }
            image = b'\xff' * 0xcf0000
            metadata = {'window_sha256': sha(image)}
            templates = {name: template_elf() for name in HELPERS}
            first = make_bundle(templates, image, metadata, stock, root / 'bundle-one')
            second = make_bundle(templates, image, metadata, stock, root / 'bundle-two')
            self.assertNotEqual(first['nonce'], second['nonce'])
            for name in HELPERS[2:]:
                data = (root / 'bundle-one' / name).read_bytes()
                start, length = policy_span(data)
                policy = data[start:start + length]
                for at, child in ((618, HELPERS[0]), (683, HELPERS[1])):
                    self.assertEqual(policy[at:at + 65],
                                     first['files'][child]['sha256'].encode('ascii') + b'\0')
            saved = json.loads((root / 'bundle-one' / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(saved, first)
            self.assertFalse((root / 'bundle-one' / 'rehearsal.json').exists())
            path.write_bytes(backup[:-1] + b'\0')
            with self.assertRaisesRegex(ValueError, 'Backup changed'):
                make_bundle(templates, image, metadata, stock, root / 'changed-backup')
            self.assertFalse((root / 'changed-backup').exists())


if __name__ == '__main__':
    unittest.main()
