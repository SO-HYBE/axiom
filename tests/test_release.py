"""Offline packaging tests use explicitly synthetic source and run fixtures."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from axiom import release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'synthetic-project'
        self.root.mkdir()
        self.output = Path(self.temp.name) / 'release'
        for name in release.ROOT_FILES:
            self.write(name, b'Synthetic public setup text.\n')
        self.write('src/axiom/app.py', b'# Synthetic code.\n')
        self.write('src/axiom/web/index.html', b'<main>Synthetic UI</main>')
        self.write('tests/test_synthetic.py', b'# Synthetic test.\n')
        self.write('docs/SETUP.md', b'Synthetic setup guide.\n')
        self.write('benchmarks/questions.jsonl', b'{}\n')
        self.json('data/sources.json', {'sources': []})
        self.json('data/benchmark_sources.json', {'sources': []})
        self.write('data/processed/chunks.jsonl', b'')
        self.json('data/processed/manifest.json', {'sources': [], 'chunk_count': 0,
            'corpus_sha256': hashlib.sha256(b'').hexdigest(),
            'sources_inventory_sha256': hashlib.sha256((self.root / 'data/sources.json').read_bytes()).hexdigest()})
        for identifier in ('20160000593', '20150023456'):
            self.json('data/raw/ntrs-' + identifier + '.json', {'synthetic': True})
            self.json('data/raw/ntrs-' + identifier + '.json.provenance.json', {'synthetic': True})
        for identifier in release.RUN_IDS:
            base = 'runs/benchmarks/' + identifier
            self.json(base + '/manifest.json', {'run_id': identifier,
                'jobs': [{'question_id': 'Q001', 'system': 'ignis'}],
                'inputs': {'code_sha256': {'critic.py': 'synthetic-digest'}}})
            self.json(base + '/report.json', {'progress': {'overall': {
                'scheduled': 108, 'completed': 103, 'failed': 2, 'pending': 3, 'graded': 0}}})
            self.write(base + '/corpus_snapshot.json', b'[]')
            self.write(base + '/conditions_snapshot.json', b'[]')
            self.write(base + '/jobs/Q001--ignis.json', b'{"fixture":true}')
            self.write(base + '/code_snapshot/critic.py', b'# Synthetic frozen code.\n')
            self.write(base + '/review_key.private.json', b'{"private":"MUST NOT BUNDLE"}')
            self.write(base + '/.write.lock', b'0')
        self.write('.env', b'GROQ_KEY=synthetic-package-secret\n')
        self.write('.git/config', b'Synthetic local git configuration.')
        self.write('runs/model_cache/secret.json', b'MUST NOT BUNDLE')
        self.write('personal-notes.txt', b'MUST NOT BUNDLE')

    def write(self, name, blob):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)

    def json(self, name, value):
        self.write(name, json.dumps(value).encode())

    def build(self):
        return release.build_release(self.root, self.output)

    def rewrite_archive(self, transform):
        archive = self.output / release.ARCHIVE_NAME
        with zipfile.ZipFile(archive) as package:
            values = [(info.filename, package.read(info.filename)) for info in package.infolist()]
        values = transform(values)
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            for name, blob in values:
                package.writestr(name, blob)

    def test_includes_runnable_sources_and_frozen_data_but_excludes_private_files(self):
        result = self.build()
        self.assertTrue(result['verified'])
        self.assertEqual(result['benchmark_status']['completed'], 103)
        with zipfile.ZipFile(result['archive']) as package:
            names = set(package.namelist())
            self.assertIn('src/axiom/app.py', names)
            self.assertIn('data/processed/chunks.jsonl', names)
            self.assertIn('runs/benchmarks/' + release.PRIMARY_RUN + '/jobs/Q001--ignis.json', names)
            self.assertFalse(any('private' in name or '.env' in name or '.git' in name or 'model_cache' in name for name in names))
            self.assertNotIn('personal-notes.txt', names)
            self.assertNotIn(b'synthetic-package-secret', b''.join(package.read(name) for name in names))

    def test_identical_inputs_produce_identical_archives_and_sidecar_hash(self):
        first = self.build()
        second = release.build_release(self.root, self.output.parent / 'another-release')
        self.assertEqual(first['archive_sha256'], second['archive_sha256'])
        self.assertEqual(Path(first['archive']).read_bytes(), Path(second['archive']).read_bytes())
        digest = hashlib.sha256(Path(first['archive']).read_bytes()).hexdigest()
        self.assertTrue((self.output / (release.ARCHIVE_NAME + '.sha256')).read_text().startswith(digest))
        self.assertTrue(release.verify_release(self.output)['verified'])

    def test_exact_offline_wheels_launchers_and_demo_manifest_are_admitted(self):
        self.write('launch.ps1', b'# Synthetic launcher')
        self.write('launch.cmd', b'@echo off')
        self.json('data/demo.json', {'synthetic': True})
        for name in release.WHEELS:
            self.write('wheelhouse/' + name, b'Synthetic wheel bytes')
        self.write('wheelhouse/unknown-model.whl', b'MUST NOT BUNDLE')
        result = self.build()
        with zipfile.ZipFile(result['archive']) as package:
            self.assertIn('data/demo.json', package.namelist())
            self.assertIn('launch.ps1', package.namelist())
            self.assertIn('wheelhouse/' + release.WHEELS[0], package.namelist())
            self.assertNotIn('wheelhouse/unknown-model.whl', package.namelist())

    def test_modified_payload_is_rejected(self):
        self.build()
        self.rewrite_archive(lambda values: [(name, b'TAMPERED' if name == 'README.md' else blob) for name, blob in values])
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            release.verify_release(self.output)

    def test_extra_member_and_case_colliding_paths_are_rejected(self):
        for extra in ('docs/UNLISTED.md', 'readme.md'):
            with self.subTest(extra=extra):
                self.build()
                self.rewrite_archive(lambda values: values + [(extra, b'Synthetic extra')])
                with self.assertRaises(ValueError):
                    release.verify_release(self.output)

    def test_traversal_private_and_arbitrary_root_members_are_rejected(self):
        for extra in ('../outside.txt', '/absolute.txt', 'docs/../../outside', '.env',
                      'runs/benchmarks/' + release.PRIMARY_RUN + '/review_key.private.json', 'credentials.txt'):
            with self.subTest(extra=extra):
                self.build()
                self.rewrite_archive(lambda values: values + [(extra, b'Synthetic extra')])
                with self.assertRaises(ValueError):
                    release.verify_release(self.output)

    def test_configured_credentials_cannot_enter_even_an_allowlisted_source(self):
        self.write('src/axiom/app.py', b'key = "synthetic-package-secret"')
        with self.assertRaisesRegex(ValueError, 'configured provider credential'):
            self.build()
        self.assertFalse((self.output / release.ARCHIVE_NAME).exists())

    def test_corrupt_core_or_named_source_is_rejected_before_packaging(self):
        self.write('data/processed/chunks.jsonl', b'Corrupted source text')
        with self.assertRaisesRegex(ValueError, 'Core corpus'):
            self.build()
        self.write('data/processed/chunks.jsonl', b'')
        self.write('data/raw/named/synthetic-record.bin', b'Synthetic bytes')
        self.json('data/raw/named/synthetic-record.bin.provenance.json', {'sha256': 'wrong', 'bytes': 15})
        self.json('data/processed/named_sources/synthetic.json', [])
        self.json('data/benchmark_sources.json', {'sources': [{'status': 'active',
            'assets': [{'path': 'data/raw/named/synthetic-record.bin', 'key': 'record', 'sha256': 'wrong', 'bytes': 15}],
            'derived_path': 'data/processed/named_sources/synthetic.json', 'derived_sha256': 'wrong'}]})
        with self.assertRaisesRegex(ValueError, 'Named source'):
            self.build()

    def test_named_asset_cannot_redirect_allowlist(self):
        self.json('data/benchmark_sources.json', {'sources': [{'status': 'active',
            'assets': [{'path': '../outside.bin'}], 'derived_path': 'data/processed/named_sources/test.json'}]})
        with self.assertRaisesRegex(ValueError, 'raw asset path'):
            self.build()

    def test_size_limits_and_missing_required_sources_fail_before_export(self):
        with patch.object(release, 'MAX_TOTAL_BYTES', 20), self.assertRaisesRegex(ValueError, 'total size'):
            self.build()
        (self.root / 'pyproject.toml').unlink()
        with self.assertRaisesRegex(ValueError, 'Required release file'):
            self.build()

    def test_accounting_must_balance(self):
        self.json('runs/benchmarks/' + release.PRIMARY_RUN + '/report.json', {'progress': {'overall': {
            'scheduled': 108, 'completed': 104, 'failed': 2, 'pending': 3, 'graded': 0}}})
        with self.assertRaisesRegex(ValueError, 'does not balance'):
            self.build()

    def test_symlinked_allowlisted_source_is_rejected(self):
        path = self.root / 'docs/SETUP.md'
        path.unlink()
        outside = self.root.parent / 'outside.md'
        outside.write_text('Synthetic private outside text.')
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest('Symlink creation unavailable on this host')
        with self.assertRaisesRegex(ValueError, 'Redirected'):
            self.build()


if __name__ == '__main__':
    unittest.main()
