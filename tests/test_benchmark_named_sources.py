import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom import benchmark_named_sources as named
from test_archived_source import html as archived_html, provenance as archived_provenance


class NamedSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = copy.deepcopy(named.BY_ID['psi-69'])
        self.record = dict(accession='PSI-69', version=5, public=True, restricted=False,
                           licenseIdentifier='CC0-1.0', licenseLink='https://spdx.org/licenses/CC0-1.0.html',
                           doi='10.60555/mbq8-0451', objective='Synthetic liquid droplet objective.',
                           approach='<p>Synthetic 0.5 mW method.</p>',
                           experimentalTable='MUST NOT ENTER SELECTED TEXT')

    def assets(self):
        return {'record': json.dumps(self.record).encode()}

    def fetch(self, url, body=None):
        blob = self.assets()['record']
        return blob, dict(url=url, final_url=url, method='GET', request_body_sha256=None,
                          retrieved_at='2026-11-06T00:00:00+00:00', sha256=hashlib.sha256(blob).hexdigest(),
                          bytes=len(blob), content_type='application/json')

    def collect(self):
        with patch.object(named, 'SPECS', [self.spec]), patch.object(named, '_fetch', self.fetch):
            return named.collect_named_sources(self.root)

    def test_absent_manifest_is_empty_offline(self):
        self.assertEqual(named.load_named_chunks(self.root), [])
        self.assertEqual(named.load_named_inventory(self.root), [])

    def test_archived_original_is_cached_and_replayed_with_explicit_identity(self):
        spec = named.BY_ID['named-flex-blog']
        blob = archived_html()
        with patch.object(named, 'SPECS', [spec]), \
             patch.object(named, 'fetch_archived_blog', return_value=(blob, archived_provenance(blob))) as fetch, \
             patch.object(named, '_fetch', side_effect=AssertionError('Do not widen the NASA downloader')):
            result = named.collect_named_sources(self.root)
        self.assertEqual(result['active_sources'], 1)
        self.assertEqual(result['failed_sources'], 0)
        fetch.assert_called_once_with(named.ARCHIVE_URL)
        chunks = named.load_named_chunks(self.root)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]['url'], named.ORIGINAL_URL)
        self.assertEqual(chunks[0]['document_url'], named.ARCHIVE_URL)
        self.assertEqual(chunks[0]['archive_as_of'], named.ARCHIVE_AS_OF)
        self.assertEqual(chunks[0]['publication_date'], '2013-11-25')
        self.assertTrue(all(value is None for chunk in chunks for value in chunk['conditions'].values()))
        with patch.object(named, 'fetch_archived_blog', side_effect=AssertionError('Offline replay only')):
            self.assertEqual(named.load_named_chunks(self.root), chunks)

    def test_archive_capture_provenance_cannot_be_changed_in_sidecar_and_manifest(self):
        spec = named.BY_ID['named-flex-blog']
        with patch.object(named, 'SPECS', [spec]), \
             patch.object(named, 'fetch_archived_blog', return_value=(archived_html(), archived_provenance())):
            named.collect_named_sources(self.root)
        path = self.root / 'data/raw/named/named-flex-blog-article.bin.provenance.json'
        sidecar = json.loads(path.read_bytes())
        sidecar['archive_as_of'] = '2026-01-01T00:00:00+00:00'
        path.write_bytes(named._encoded(sidecar))
        manifest = json.loads((self.root / named.MANIFEST).read_bytes())
        manifest['sources'][0]['assets'][0]['archive_as_of'] = sidecar['archive_as_of']
        (self.root / named.MANIFEST).write_bytes(named._encoded(manifest))
        with self.assertRaisesRegex(ValueError, 'capture mismatch'):
            named.load_named_chunks(self.root)

    def test_selects_only_named_fields_preserves_units_and_unknown_conditions(self):
        chunks, rights = named._extract(self.spec, self.assets())
        self.assertEqual([c['section'] for c in chunks], ['Objectives', 'Approach'])
        self.assertEqual(chunks[1]['text'], 'Synthetic 0.5 mW method.')
        self.assertNotIn('MUST NOT', json.dumps(chunks))
        self.assertTrue(all(c['evidence_role'] == 'source_description' and c['named_scope_verified'] for c in chunks))
        self.assertTrue(all(v is None for c in chunks for v in c['conditions'].values()))
        self.assertEqual(rights['statement'], 'CC0-1.0')

    def test_wrong_identity_version_access_or_license_rejected(self):
        for key, value in [('accession', 'PSI-25'), ('version', True), ('version', 4), ('public', False),
                           ('restricted', True), ('licenseIdentifier', 'unknown'), ('doi', 'invented'),
                           ('licenseLink', 'https://example.invalid/terms')]:
            with self.subTest(key=key, value=value):
                record = dict(self.record, **{key: value})
                with self.assertRaises(ValueError):
                    named._extract(self.spec, {'record': json.dumps(record).encode()})

    def test_files_preserves_publisher_paths_without_reading_measurements(self):
        tree = [dict(displayName='Raw Data', visible=True, restricted=False, restrictedAccess=False,
                     files=[dict(key='psi-data/PSI-98/Raw Data/test.csv', visible=True, restricted=False,
                                 restrictedAccess=False),
                            dict(key='secret.csv', visible=True, restricted=True, restrictedAccess=True)])]
        self.assertEqual(named._file_names(tree), ['Raw Data', 'psi-data/PSI-98/Raw Data/test.csv'])
        self.assertEqual(named._file_names([{'key': 'unknown-access.csv'}]), [])

    def test_files_chunk_hash_points_to_listing_bytes(self):
        spec = named.BY_ID['psi-98']
        record = dict(self.record, accession='PSI-98', version=4, doi='10.60555/0t15-1z43')
        files = {'files': [dict(key='psi-data/PSI-98/Synthetic.csv', visible=True,
                                restricted=False, restrictedAccess=False)]}
        def fetch(url, body=None):
            blob = json.dumps(files if body else record).encode()
            return blob, dict(url=url, final_url=url, method='POST' if body else 'GET',
                request_body_sha256=named._digest(named._encoded(body)) if body else None,
                retrieved_at='2026-11-06T00:00:00+00:00', sha256=named._digest(blob),
                bytes=len(blob), content_type='application/json')
        with patch.object(named, 'SPECS', [spec]), patch.object(named, '_fetch', fetch):
            named.collect_named_sources(self.root)
        chunks = named.load_named_chunks(self.root)
        listing = next(c for c in chunks if c['section'] == 'Files')
        objective = next(c for c in chunks if c['section'] == 'Objectives')
        self.assertEqual(listing['source_sha256'], named._digest(json.dumps(files).encode()))
        self.assertNotEqual(listing['source_sha256'], objective['source_sha256'])

    def test_rtdfs_scope_excludes_adjacent_sections(self):
        html = b'<main><article><div class="entry-content"><h2>Science Objectives</h2><p>Synthetic theoretical objective.</p><h2>Status</h2><p>OUTSIDE SCOPE</p></div></article></main>'
        chunks, _ = named._extract(named.BY_ID['named-rtdfs'], {'article': html})
        self.assertEqual([c['text'] for c in chunks], ['Synthetic theoretical objective.'])
        self.assertEqual(chunks[0]['section'], 'Science Objectives')

    def test_flex_section_requires_unique_headings_and_bounded_end(self):
        rights = json.dumps(dict(id=20150023456, distribution='PUBLIC',
                                 copyright={'determinationType': 'PUBLIC_USE_PERMITTED'})).encode()
        text = b'Contents: 4.2 Analyzed Data ... 16\n4.2 Analyzed Data\nSynthetic 0.5 mW exact prose.\n5.0 Observations and Discussion\nOUTSIDE SCOPE'
        assets = {'text': text, 'rights': rights}
        chunks, _ = named._extract(named.BY_ID['ntrs-20150023456'], assets)
        self.assertEqual(chunks[0]['text'], 'Synthetic 0.5 mW exact prose.')
        for invalid in [text.replace(b'5.0 Observations and Discussion', b'MISSING'),
                        text + b'\n4.2 Analyzed Data\nDuplicate heading']:
            with self.assertRaises(ValueError):
                named._extract(named.BY_ID['ntrs-20150023456'], dict(assets, text=invalid))

    def test_cache_replay_is_offline_and_unchanged_ingest_is_stable(self):
        self.collect()
        before = (self.root / named.MANIFEST).read_bytes()
        with patch.object(named, 'SPECS', [self.spec]), patch.object(named, '_fetch', side_effect=AssertionError('No network')):
            named.collect_named_sources(self.root)
            chunks = named.load_named_chunks(self.root)
        self.assertEqual((self.root / named.MANIFEST).read_bytes(), before)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]['source_sha256'], hashlib.sha256(self.assets()['record']).hexdigest())

    def test_raw_corruption_and_forged_derived_text_fail_closed(self):
        self.collect()
        raw = self.root / 'data/raw/named/psi-69-record.bin'
        original = raw.read_bytes()
        raw.write_bytes(original + b' ')
        with self.assertRaisesRegex(ValueError, 'provenance'):
            named.load_named_chunks(self.root)
        raw.write_bytes(original)
        path = self.root / 'data/processed/named_sources/psi-69.json'
        data = json.loads(path.read_bytes())
        data[0]['text'] = 'FORGED SCIENCE'
        forged = named._encoded(data)
        path.write_bytes(forged)
        manifest = json.loads((self.root / named.MANIFEST).read_bytes())
        manifest['sources'][0]['derived_sha256'] = hashlib.sha256(forged).hexdigest()
        (self.root / named.MANIFEST).write_bytes(named._encoded(manifest))
        with self.assertRaisesRegex(ValueError, 'extraction'):
            named.load_named_chunks(self.root)

    def test_sidecar_and_manifest_paths_cannot_redirect_source_identity(self):
        self.collect()
        path = self.root / 'data/raw/named/psi-69-record.bin.provenance.json'
        original = path.read_bytes()
        sidecar = json.loads(original)
        sidecar['url'] = 'https://example.invalid/fake'
        path.write_bytes(named._encoded(sidecar))
        with self.assertRaises(ValueError):
            named.load_named_chunks(self.root)
        path.write_bytes(original)
        manifest = json.loads((self.root / named.MANIFEST).read_bytes())
        manifest['sources'][0]['assets'][0]['path'] = '../outside.bin'
        (self.root / named.MANIFEST).write_bytes(named._encoded(manifest))
        with self.assertRaises(ValueError):
            named.load_named_chunks(self.root)

    def test_collection_failure_is_pending_not_fabricated_text(self):
        with patch.object(named, 'SPECS', [self.spec]), patch.object(named, '_fetch', side_effect=OSError('Synthetic unavailable source')):
            result = named.collect_named_sources(self.root)
        self.assertEqual(result['active_sources'], 0)
        self.assertEqual(result['sources'][0]['status'], 'unavailable')
        self.assertEqual(named.load_named_chunks(self.root), [])

    def test_size_limits_duplicate_keys_and_duplicate_source_ids_rejected(self):
        with self.assertRaises(ValueError):
            named._write(self.root, 'data/too-large', b'x' * (named.MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            named._json(b'{"accession":"PSI-69","accession":"PSI-25"}')
        with self.assertRaises(ValueError):
            named._json(b'[]')
        self.collect()
        path = self.root / named.MANIFEST
        value = json.loads(path.read_bytes())
        value['sources'].append(value['sources'][0])
        path.write_bytes(named._encoded(value))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            named.load_named_chunks(self.root)


if __name__ == '__main__':
    unittest.main()
