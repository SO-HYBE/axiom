import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from axiom.benchmark_scope import load_scope_chunks
from axiom.retrieval import eligible


class BenchmarkScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data/raw').mkdir(parents=True)
        self.identifier = '20160000593'
        self.source = {
            'source_id': 'ntrs-' + self.identifier, 'ntrs_id': self.identifier,
            'url': 'https://ntrs.nasa.gov/citations/' + self.identifier,
            'metadata_url': 'https://ntrs.nasa.gov/api/citations/' + self.identifier,
            'permission_status': 'allowed', 'status': 'active',
            'experiment': 'BASS-II', 'evidence_tier': 2,
        }
        self.metadata = {
            'id': int(self.identifier), 'title': 'Synthetic test document',
            'stiType': 'PRESENTATION', 'distribution': 'PUBLIC',
            'copyright': {'determinationType': 'PUBLIC_USE_PERMITTED'},
            'abstract': 'Synthetic ABSTRACT: preserve mW versus MW and 0 to 5 cms.',
            'body': 'This full-report field must not enter the chunk.',
        }
        self.path = self.root / 'data/raw' / (self.source['source_id'] + '.json')
        self.sidecar = self.path.with_name(self.path.name + '.provenance.json')
        self.write_inventory()
        self.write_cache()

    def write_inventory(self, sources=None):
        (self.root / 'data/sources.json').write_text(
            json.dumps({'sources': sources if sources is not None else [self.source]}), encoding='utf-8')

    def write_cache(self):
        data = json.dumps(self.metadata, ensure_ascii=False).encode('utf-8')
        self.path.write_bytes(data)
        self.provenance = {
            'url': self.source['metadata_url'], 'final_url': self.source['metadata_url'],
            'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'retrieved_at': '2026-11-05T00:00:00+00:00', 'content_type': 'application/json; charset=utf-8',
        }
        self.write_provenance()

    def write_provenance(self):
        self.sidecar.write_text(json.dumps(self.provenance), encoding='utf-8')

    def test_extracts_only_abstract_and_preserves_exact_text(self):
        result = load_scope_chunks(self.root)
        self.assertEqual(len(result), 1)
        chunk = result[0]
        self.assertEqual(chunk['text'], self.metadata['abstract'])
        self.assertEqual(chunk['locator'], 'NTRS metadata abstract')
        self.assertEqual(chunk['source_kind'], 'presentation_abstract')
        self.assertIsNone(chunk['document_url'])
        self.assertEqual(chunk['source_sha256'], self.provenance['sha256'])
        self.assertEqual(chunk['sha256'], hashlib.sha256(chunk['text'].encode()).hexdigest())
        self.assertTrue(chunk['chunk_id'].startswith('ntrs-20160000593-abstract-'))
        self.assertTrue(all(value is None for value in chunk['conditions'].values()))
        self.assertTrue(eligible(chunk, None, None, False))
        self.assertEqual(result, load_scope_chunks(self.root))

    def test_missing_inventory_or_metadata_returns_empty(self):
        self.path.unlink()
        self.assertEqual(load_scope_chunks(self.root), [])
        (self.root / 'data/sources.json').unlink()
        self.assertEqual(load_scope_chunks(self.root), [])

    def test_missing_sidecar_rejects_present_metadata(self):
        self.sidecar.unlink()
        with self.assertRaises(ValueError):
            load_scope_chunks(self.root)

    def test_modified_metadata_hash_rejected(self):
        self.path.write_bytes(self.path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'provenance mismatch'):
            load_scope_chunks(self.root)

    def test_provenance_url_hash_and_size_mismatches_rejected(self):
        for field, value in (
            ('sha256', '0' * 64), ('bytes', True), ('bytes', 1),
            ('url', 'http://ntrs.nasa.gov/api/citations/20160000593'),
            ('final_url', 'https://ntrs.nasa.gov.evil.example/api/citations/20160000593'),
            ('final_url', 'https://ntrs.nasa.gov/api/citations/20150023456'),
        ):
            with self.subTest(field=field, value=value):
                self.write_cache()
                self.provenance[field] = value
                self.write_provenance()
                with self.assertRaises(ValueError):
                    load_scope_chunks(self.root)

    def test_inventory_identity_and_url_mismatches_rejected(self):
        for field, value in (
            ('ntrs_id', '../20160000593'),
            ('metadata_url', 'https://ntrs.nasa.gov/api/citations/20160000593?extra=1'),
            ('url', 'https://user@ntrs.nasa.gov/citations/20160000593'),
        ):
            with self.subTest(field=field):
                self.write_inventory([{**self.source, field: value}])
                with self.assertRaises(ValueError):
                    load_scope_chunks(self.root)

    def test_unknown_inventory_paths_are_not_read(self):
        self.write_inventory([{**self.source, 'source_id': '../../outside'}])
        self.assertEqual(load_scope_chunks(self.root), [])

    def test_metadata_record_id_and_type_rejected(self):
        for field, value in (('id', '20160000593'), ('id', 20150023456), ('id', True), ('stiType', 'UNKNOWN')):
            with self.subTest(field=field, value=value):
                original = self.metadata[field]
                self.metadata[field] = value
                self.write_cache()
                with self.assertRaises(ValueError):
                    load_scope_chunks(self.root)
                self.metadata[field] = original

    def test_inventory_permission_and_quarantine_exclude_source(self):
        for change in ({'permission_status': 'review_required'}, {'status': 'quarantined'}):
            self.write_inventory([{**self.source, **change}])
            self.assertEqual(load_scope_chunks(self.root), [])

    def test_restricted_metadata_distribution_or_rights_rejected(self):
        self.metadata['distribution'] = 'RESTRICTED'
        self.write_cache()
        with self.assertRaises(ValueError):
            load_scope_chunks(self.root)
        self.metadata['distribution'] = 'PUBLIC'
        self.metadata['copyright']['determinationType'] = 'MAY_INCLUDE_COPYRIGHT_MATERIAL'
        self.write_cache()
        with self.assertRaises(ValueError):
            load_scope_chunks(self.root)

    def test_empty_abstract_does_not_invent_content(self):
        self.metadata['abstract'] = '   '
        self.write_cache()
        self.assertEqual(load_scope_chunks(self.root), [])

    def test_duplicate_inventory_entry_rejected(self):
        self.write_inventory([self.source, dict(self.source)])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            load_scope_chunks(self.root)

    def test_deferred_report_can_supply_its_abstract(self):
        self.identifier = '20150023456'
        self.source.update(source_id='ntrs-' + self.identifier, ntrs_id=self.identifier,
                           url='https://ntrs.nasa.gov/citations/' + self.identifier,
                           metadata_url='https://ntrs.nasa.gov/api/citations/' + self.identifier,
                           status='large_file_deferred', experiment='FLEX', evidence_tier=1)
        self.metadata.update(id=int(self.identifier), stiType='TECHNICAL_PUBLICATION')
        self.path = self.root / 'data/raw' / (self.source['source_id'] + '.json')
        self.sidecar = self.path.with_name(self.path.name + '.provenance.json')
        self.write_inventory()
        self.write_cache()
        chunk = load_scope_chunks(self.root)[0]
        self.assertEqual(chunk['source_kind'], 'technical_report_abstract')
        self.assertEqual(chunk['source_inventory_status'], 'large_file_deferred')
        self.assertEqual(chunk['status'], 'active')
        self.assertIsNone(chunk['document_url'])

    def test_cache_symlink_outside_root_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'metadata.json'
            target.write_bytes(self.path.read_bytes())
            self.path.unlink()
            try:
                self.path.symlink_to(target)
            except OSError:
                self.skipTest('OS does not permit symlinks for this test process')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                load_scope_chunks(self.root)


if __name__ == '__main__':
    unittest.main()
