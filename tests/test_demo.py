"""Offline replay integrity tests; all scientific text here is synthetic."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.benchmark_run import _directory, _hash, _read, _write
from axiom.demo import CASES, RUN_ID, get_demo, list_demos, prepare_demos


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = _directory(self.root, RUN_ID)
        self.directory.mkdir(parents=True)
        text = 'Synthetic investigation objective: study liquid droplets.'
        self.chunk = dict(chunk_id='synthetic-chunk', source_id='synthetic-source',
                          text=text, sha256=hashlib.sha256(text.encode()).hexdigest(),
                          locator='Synthetic Objectives', url='https://example.invalid/source')
        scope = [dict(question_id=case['question_id'], allowed_chunk_ids=['synthetic-chunk'],
                      all_reference_scopes_available=True) for case in CASES]
        self.inputs = dict(corpus_sha256=_hash([self.chunk]), scope_plan=scope)
        self.manifest = dict(run_id=RUN_ID, inputs=self.inputs, input_fingerprint=_hash(self.inputs),
            jobs=[dict(question_id=case['question_id'], system='ignis', split='dev', block_reason=None)
                  for case in CASES])
        _write(self.directory / 'corpus_snapshot.json', [self.chunk])
        citation = dict(source_id=self.chunk['source_id'], chunk_id=self.chunk['chunk_id'], quote=text)
        self.claim = dict(text=text, citations=[citation], verdict='model_supported_needs_review')
        self.records = {}
        for index, case in enumerate(CASES):
            claims = [deepcopy(self.claim)] if index == 0 else []
            checks = [dict(deepcopy(self.claim), issues=['condition_unknown:pressure_kpa'], verdict='needs_review')] if index == 1 else []
            run = dict(run_id='saved-' + case['id'], question='Synthetic question ' + case['id'],
                       system='ignis', mode='model', answer='Synthetic saved answer.',
                       abstained=index != 0, claims=claims, draft_checks=checks,
                       raw_draft=dict(claims=claims, abstained=index != 0, reason='Synthetic rationale.'),
                       evidence=[deepcopy(self.chunk)],
                       evidence_selection={'mode':'explicit_source_scope' if index == 2 else 'lexical_search',
                                           'explicit_scope_complete':index == 2},
                       model_calls=[{'status': 'success'}] if index != 2 else [],
                       notice='Original historical notice', error=None)
            prediction = dict(question_id=case['question_id'], system='ignis',
                              answer=run['answer'], abstained=run['abstained'], claims=deepcopy(claims))
            record = dict(question_id=case['question_id'], system='ignis',
                          input_fingerprint=self.manifest['input_fingerprint'], run=run, prediction=prediction)
            self.records[case['question_id']] = record
        self.save()

    def save(self):
        self.manifest['input_fingerprint'] = _hash(self.manifest['inputs'])
        _write(self.directory / 'manifest.json', self.manifest)
        for question_id, record in self.records.items():
            record['input_fingerprint'] = self.manifest['input_fingerprint']
            data = deepcopy(record)
            data['record_sha256'] = _hash(data)
            _write(self.directory / 'jobs' / (question_id + '--ignis.json'), data)

    def test_three_actual_behavior_shapes_replay_offline_without_mutation(self):
        prepare_demos(self.root)
        path = self.directory / 'jobs/Q002--ignis.json'
        original = path.read_bytes()
        with patch('axiom.benchmark_run.make_model', side_effect=AssertionError('No inference')), \
             patch('urllib.request.urlopen', side_effect=AssertionError('No network')):
            cards = list_demos(self.root)
            answered = get_demo(self.root, 'source-description')
            withheld = get_demo(self.root, 'scope-check')
            gap = get_demo(self.root, 'insufficient-measurements')
        self.assertEqual([card['id'] for card in cards], [case['id'] for case in CASES])
        self.assertFalse(answered['run']['abstained'])
        self.assertTrue(withheld['run']['abstained'])
        self.assertTrue(gap['run']['evidence'])
        self.assertTrue(gap['run']['evidence_selection']['explicit_scope_complete'])
        self.assertTrue(all(card['replay'] and card['model_calls_made'] == 0 for card in cards))
        self.assertIn('no new model request', answered['notice'])
        self.assertTrue(answered['run']['replay']['saved'])
        self.assertEqual(answered['run']['replay']['model_calls_made'], 0)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(_read(path)['run']['notice'], 'Original historical notice')

    def test_unchanged_preparation_is_deterministic(self):
        prepare_demos(self.root)
        path = self.root / 'data/demo.json'
        original = path.read_bytes()
        prepare_demos(self.root)
        self.assertEqual(path.read_bytes(), original)

    def test_absent_manifest_has_no_demo_cards_and_unknown_id_is_rejected(self):
        self.assertEqual(list_demos(self.root), [])
        with self.assertRaisesRegex(ValueError, 'Unknown demonstration'):
            get_demo(self.root, '../outside')

    def test_missing_job_is_not_replaced_with_a_fabricated_answer(self):
        prepare_demos(self.root)
        (self.directory / 'jobs/Q008--ignis.json').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            get_demo(self.root, 'scope-check')

    def test_corrupt_record_digest_fails_before_display(self):
        prepare_demos(self.root)
        path = self.directory / 'jobs/Q002--ignis.json'
        value = _read(path)
        value['run']['answer'] = 'Forged saved answer'
        _write(path, value)
        with self.assertRaisesRegex(ValueError, 'frozen benchmark'):
            get_demo(self.root, 'source-description')

    def test_rehashed_record_cannot_bypass_the_pinned_demo_digest(self):
        prepare_demos(self.root)
        self.records['Q002']['run']['answer'] = 'Replaced answer'
        self.records['Q002']['prediction']['answer'] = 'Replaced answer'
        self.save()
        with self.assertRaisesRegex(ValueError, 'record changed'):
            get_demo(self.root, 'source-description')

    def test_changed_frozen_corpus_fails_integrity(self):
        prepare_demos(self.root)
        _write(self.directory / 'corpus_snapshot.json', [])
        with self.assertRaisesRegex(ValueError, 'corpus snapshot'):
            get_demo(self.root, 'source-description')

    def test_evidence_outside_named_scope_cannot_be_prepared(self):
        self.manifest['inputs']['scope_plan'][0]['allowed_chunk_ids'] = []
        self.save()
        with self.assertRaisesRegex(ValueError, 'outside its frozen source scope'):
            prepare_demos(self.root)

    def test_fabricated_quote_or_source_id_cannot_be_prepared(self):
        record = deepcopy(self.records['Q002'])
        for changes in ({'quote': 'Invented text'}, {'source_id': 'wrong-source'}):
            with self.subTest(changes=changes):
                self.records['Q002'] = deepcopy(record)
                for field in ('run', 'prediction'):
                    self.records['Q002'][field]['claims'][0]['citations'][0].update(changes)
                self.save()
                with self.assertRaisesRegex(ValueError, 'citation is not traceable'):
                    prepare_demos(self.root)

    def test_failed_execution_and_replaced_prediction_cannot_be_prepared(self):
        self.records['Q002']['prediction']['execution_error'] = 'Synthetic failure'
        self.save()
        with self.assertRaisesRegex(ValueError, 'failed execution'):
            prepare_demos(self.root)
        del self.records['Q002']['prediction']['execution_error']
        self.records['Q002']['prediction']['answer'] = 'Different exported answer'
        self.save()
        with self.assertRaisesRegex(ValueError, 'differs from its recorded answer'):
            prepare_demos(self.root)

    def test_manifest_cannot_redirect_or_relabel_a_demo(self):
        prepare_demos(self.root)
        path = self.root / 'data/demo.json'
        original = _read(path)
        for mutation in ('path', 'duplicate', 'behavior'):
            value = deepcopy(original)
            if mutation == 'path':
                value['benchmark_run_id'] = '../outside'
            elif mutation == 'duplicate':
                value['demos'][1]['id'] = value['demos'][0]['id']
            else:
                value['demos'][2]['behavior'] = 'scientifically_proven'
            _write(path, value)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                list_demos(self.root)

    def test_declared_behavior_must_match_recorded_observations(self):
        self.records['Q008']['run']['draft_checks'] = []
        self.save()
        with self.assertRaisesRegex(ValueError, 'Scope-withholding'):
            prepare_demos(self.root)


if __name__ == '__main__':
    unittest.main()
