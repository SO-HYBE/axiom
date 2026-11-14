import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from axiom.run_records import (MAX_RECORD_BYTES, load_comparison, load_run, list_comparisons,
                               list_runs, save_comparison, save_run)


class RunRecordTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def run_record(self, identifier='fixture-run', **fields):
        return {'run_id': identifier, 'answer': 'A fixture answer.', **fields}

    def comparison(self, identifier='comparison-1', **fields):
        return {'comparison_id': identifier, 'created_at': '2026-11-04T10:00:00+00:00',
                'question': 'A synthetic comparison?', 'baseline': self.run_record('baseline'),
                'ignis': self.run_record('ignis', answer_status='model_checked_summary'),
                'controls': {'experiments': ['BASS']}, 'status': 'complete', 'errors': {}, **fields}

    def test_run_is_saved_as_valid_json(self):
        result = self.run_record()
        path = save_run(self.root, result)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), result)
        self.assertEqual(load_run(self.root, 'fixture-run'), result)
        self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_failed_replace_preserves_existing_record_and_removes_temporary_file(self):
        original = self.run_record(answer='Original fixture.')
        path = save_run(self.root, original)
        with patch('axiom.run_records.os.replace', side_effect=OSError('Fixture disk error')):
            with self.assertRaises(OSError):
                save_run(self.root, self.run_record(answer='Replacement fixture.'))
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), original)
        self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_nested_simultaneous_save_uses_distinct_temporary_files(self):
        real_replace = os.replace
        observed = []
        def replace(source, destination):
            observed.append(source)
            if len(observed) == 1:
                save_run(self.root, self.run_record(answer='Inner write.'))
                self.assertTrue(Path(source).exists())
            real_replace(source, destination)
        with patch('axiom.run_records.os.replace', side_effect=replace):
            save_run(self.root, self.run_record(answer='Outer write.'))
        self.assertEqual(len(set(observed)), 2)
        self.assertEqual(load_run(self.root, 'fixture-run')['answer'], 'Outer write.')
        self.assertEqual(list((self.root / 'runs/history').glob('*.tmp')), [])

    def test_legacy_fields_default_without_inventing_dates(self):
        save_run(self.root, self.run_record())
        summary = list_runs(self.root)['runs'][0]
        self.assertIsNone(summary['created_at'])
        self.assertEqual(summary['question'], 'Saved answer')
        self.assertIsNone(summary['abstained'])
        self.assertIsNone(summary['provider'])

    def test_pagination_search_and_timezone_order_are_deterministic(self):
        for identifier in ('b', 'a'):
            save_run(self.root, self.run_record(identifier, created_at='2026-11-04T10:00:00Z', question='Flame query'))
        save_run(self.root, self.run_record('newest', created_at='2026-11-04T10:30:00+00:00', question='Other'))
        save_run(self.root, self.run_record('older', created_at='2026-11-04T11:00:00+02:00', question='Flame query'))
        save_run(self.root, self.run_record('legacy'))
        result = list_runs(self.root, limit=2, offset=1)
        self.assertEqual([row['run_id'] for row in result['runs']], ['a', 'b'])
        self.assertEqual(result['total'], 5)
        self.assertEqual(list_runs(self.root, query='FLAME')['total'], 3)
        self.assertEqual(list_runs(self.root, offset=99)['runs'], [])
        self.assertEqual(list_runs(self.root)['runs'][-1]['run_id'], 'legacy')

    def test_empty_directory_and_missing_record(self):
        self.assertEqual(list_runs(self.root), {'runs': [], 'total': 0, 'skipped': 0})
        self.assertEqual(list_comparisons(self.root), {'comparisons': [], 'total': 0, 'skipped': 0})
        with self.assertRaises(FileNotFoundError):
            load_run(self.root, 'missing')

    def test_ids_reject_traversal_and_reserved_shapes(self):
        for identifier in ('../outside', '/absolute', 'x/y', 'x\\y', '', '.hidden', 'a' * 101, 'bad.json', 'bad\n', None):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    save_run(self.root, self.run_record(identifier))
                with self.assertRaises(ValueError):
                    load_run(self.root, identifier)
                with self.assertRaises(ValueError):
                    load_comparison(self.root, identifier)
        save_run(self.root, self.run_record('A_0-valid'))

    def test_invalid_pagination_and_search_rejected(self):
        for fn in (list_runs, list_comparisons):
            for args in ({'limit': 0}, {'limit': 101}, {'limit': True}, {'offset': -1},
                         {'offset': 1.5}, {'query': None}, {'query': 'a' * 501}):
                with self.subTest(function=fn.__name__, args=args), self.assertRaises(ValueError):
                    fn(self.root, **args)

    def test_corrupt_mismatched_and_unreadable_records_are_skipped(self):
        path = save_run(self.root, self.run_record())
        directory = path.parent
        (directory / 'broken.json').write_text('{')
        (directory / 'mismatch.json').write_text(json.dumps(self.run_record('different')))
        (directory / 'array.json').write_text('[]')
        (directory / 'duplicate.json').write_text('{"run_id":"duplicate","run_id":"duplicate"}')
        (directory / 'no-answer.json').write_text('{"run_id":"no-answer"}')
        (directory / 'unreadable.json').mkdir()
        self.assertEqual(list_runs(self.root)['skipped'], 6)
        with self.assertRaises(ValueError):
            load_run(self.root, 'mismatch')

    def test_read_and_write_size_limits_and_nan_are_enforced(self):
        original = self.run_record()
        path = save_run(self.root, original)
        with self.assertRaises(ValueError):
            save_run(self.root, self.run_record(answer='x' * MAX_RECORD_BYTES))
        self.assertEqual(load_run(self.root, 'fixture-run'), original)
        (path.parent / 'oversized.json').write_bytes(b' ' * (MAX_RECORD_BYTES + 1))
        with self.assertRaises(ValueError):
            load_run(self.root, 'oversized')
        with self.assertRaises(ValueError):
            save_run(self.root, self.run_record(number=float('nan')))
        (path.parent / 'nonfinite.json').write_text('{"run_id":"nonfinite","number":NaN}')
        self.assertEqual(list_runs(self.root)['skipped'], 2)

    def test_comparison_roundtrip_search_and_failed_side(self):
        record = self.comparison(status='partial', baseline=None, errors={'baseline': 'Synthetic failure.'})
        before = copy.deepcopy(record)
        path = save_comparison(self.root, record)
        self.assertEqual(path.parent, self.root / 'runs/comparisons')
        self.assertEqual(load_comparison(self.root, record['comparison_id']), record)
        self.assertEqual(record, before)
        summary = list_comparisons(self.root, query='FIXTURE ANSWER')['comparisons'][0]
        self.assertEqual(summary['status'], 'partial')
        self.assertEqual(summary['ignis_status'], 'model_checked_summary')
        self.assertIsNone(summary['baseline_status'])
        self.assertNotIn('baseline', summary)

    def test_comparison_rejects_invalid_schema_and_mismatched_id(self):
        for change in ({'status': 'invented'}, {'baseline': []}, {'controls': []}, {'errors': []},
                       {'errors': {'unknown': 'bad'}}, {'question': None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                save_comparison(self.root, self.comparison(**change))
        path = save_comparison(self.root, self.comparison())
        path.write_text(json.dumps(self.comparison('wrong-id')))
        self.assertEqual(list_comparisons(self.root)['skipped'], 1)
        with self.assertRaises(ValueError):
            load_comparison(self.root, 'comparison-1')

    def test_comparison_preserves_storage_failure_details(self):
        record = self.comparison(status='partial', errors={
            'baseline_save': 'Baseline storage failed.', 'ignis_save': 'AXIOM storage failed.',
            'comparison_save': 'Earlier comparison storage failed.'})
        save_comparison(self.root, record)
        self.assertEqual(load_comparison(self.root, 'comparison-1'), record)

    def test_symlink_records_and_redirected_directory_rejected(self):
        path = save_run(self.root, self.run_record())
        target = self.root / 'outside.json'
        target.write_text(json.dumps(self.run_record('linked')))
        linked = path.parent / 'linked.json'
        try:
            linked.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation unavailable on this host')
        with self.assertRaises(ValueError):
            load_run(self.root, 'linked')
        with self.assertRaises(ValueError):
            save_run(self.root, self.run_record('linked'))
        self.assertEqual(list_runs(self.root)['skipped'], 1)
        redirected = self.root / 'redirected'
        redirected.mkdir()
        (redirected / 'runs').symlink_to(self.root / 'runs', target_is_directory=True)
        with self.assertRaises(ValueError):
            list_runs(redirected)


if __name__ == '__main__':
    unittest.main()
