"""Synthetic import fixtures are not actual reviewers or scientific grades."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.benchmark_review import MAX_BYTES, import_review
from axiom.benchmark_run import _checkpoint, _directory, _hash, _read, _write, prepare_review_packet


class BenchmarkReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_id = 'synthetic-human-import'
        self.directory = _directory(self.root, self.run_id)
        self.directory.mkdir(parents=True)
        inputs = {'questions':[{'question_id':'Q001','question':'What does this synthetic source say?'}]}
        self.manifest = dict(run_id=self.run_id, status='complete', inputs=inputs,
                             input_fingerprint=_hash(inputs), jobs=[
                                 dict(question_id='Q001', system=system, split='dev', block_reason=None)
                                 for system in ('baseline','rag_only','ignis')])
        self.records = {}
        for job in self.manifest['jobs']:
            system = job['system']
            citation = dict(source_id='synthetic-source', chunk_id='synthetic-chunk',
                             quote='Synthetic source text, never a NASA finding.')
            prediction = dict(question_id='Q001', system=system, answer='Synthetic answer.',
                              abstained=False, claims=[dict(text='Synthetic claim.', verdict='unreviewed',
                                  citations=[] if system == 'baseline' else [citation])],
                              model_calls=[], latency_ms=1)
            record = dict(question_id='Q001', system=system, prediction=prediction,
                          run={'run_id':'synthetic-' + system}, generation_scope='Synthetic named source.',
                          input_fingerprint=self.manifest['input_fingerprint'])
            self.records[system] = record
            self.save_record(system)
        _checkpoint(self.directory, self.manifest)
        prepare_review_packet(self.root, self.run_id)
        self.packet = _read(self.directory / 'review_packet.json')
        self.submission = deepcopy(self.packet)
        self.submission.update(reviewer='Synthetic reviewer fixture', qualification='Synthetic test qualification only',
                               reviewed_at='2026-11-06', independence_declaration='Synthetic independence declaration.',
                               independent=True, human_review=True, review_method='human')
        self.path = self.root / 'completed-packet-copy.json'
        for item in self.submission['items']:
            item['grading'] = {'claims':[dict(supported=True,citation_valid=bool(claim['citations']),
                                             unsafe_extrapolation=False) for claim in item['claims']],
                               'correct_abstention':True}
        self.save_submission()

    def save_record(self, system):
        record = deepcopy(self.records[system])
        record['record_sha256'] = _hash(record)
        _write(self.directory / 'jobs' / ('Q001--' + system + '.json'), record)

    def save_submission(self):
        _write(self.path, self.submission)

    def execute(self):
        with patch('axiom.benchmark_run.make_model', side_effect=AssertionError('No model grading')):
            return import_review(self.root, self.run_id, self.path)

    def test_import_is_separate_atomic_and_metadata_remains_self_reported(self):
        before = {str(path):path.read_bytes() for path in self.directory.rglob('*') if path.is_file()}
        result = self.execute()
        self.assertEqual(result['annotations_imported'], 3)
        self.assertEqual(result['pending_items'], 0)
        self.assertFalse(result['original_outputs_changed'])
        self.assertFalse(result['previous_imports_merged'])
        self.assertTrue(all(Path(path).read_bytes() == blob for path,blob in before.items()))
        annotations = [json.loads(line) for line in Path(result['annotations']).read_text().splitlines()]
        self.assertEqual(len(annotations), 3)
        report = _read(Path(result['report']))
        self.assertEqual(report['progress']['overall']['graded'], 3)
        self.assertFalse(report['is_scientific_validation'])
        reviewer = _read(Path(result['reviewer_record']))
        self.assertFalse(reviewer['qualifications_independently_verified'])
        self.assertFalse(reviewer['independence_independently_verified'])
        self.assertIn('private', Path(result['reviewer_record']).name)

    def test_partial_missing_and_atomization_items_stay_ungraded(self):
        self.submission['items'][0]['grading'] = {'status':'requires_atomization','reason':'Synthetic compound assertion.'}
        self.submission['items'] = self.submission['items'][:2]
        self.save_submission()
        result = self.execute()
        self.assertEqual(result['annotations_imported'], 1)
        self.assertEqual(result['pending_items'], 2)
        self.assertEqual(result['requires_atomization'], 1)

    def test_null_claim_label_stays_pending_and_never_becomes_false(self):
        self.submission['items'][0]['grading']['claims'][0]['supported'] = None
        self.save_submission()
        result = self.execute()
        self.assertEqual(result['annotations_imported'], 2)
        self.assertEqual(result['pending_items'], 1)
        receipt = _read(Path(result['reviewer_record']))
        self.assertEqual(receipt['ungraded_items'][0]['reason'], 'claim_grades_incomplete')

    def test_all_null_grades_leave_quality_unscored(self):
        for item in self.submission['items']:
            item['grading'] = None
        self.save_submission()
        result = self.execute()
        self.assertEqual(result['annotations_imported'], 0)
        self.assertEqual(result['pending_items'], 3)
        report = _read(Path(result['report']))
        self.assertIsNone(report['quality']['systems']['ignis']['claim_support']['value'])

    def test_no_claims_and_null_abstention_stay_pending_but_false_is_resolved(self):
        # Build a separate synthetic empty-claim packet before handing it off.
        for system,record in self.records.items():
            record['prediction']['claims']=[]
            record['prediction']['abstained']=True
            self.save_record(system)
        for name in ('review_packet.json','review_key.private.json'):
            (self.directory/name).unlink()
        _checkpoint(self.directory,self.manifest)
        prepare_review_packet(self.root,self.run_id)
        packet=_read(self.directory/'review_packet.json')
        self.submission['items']=deepcopy(packet['items'])
        self.submission['items'][0]['grading']={'claims':[],'correct_abstention':None}
        self.submission['items'][1]['grading']={'claims':[],'correct_abstention':False}
        self.submission['items'][2]['grading']={'claims':[],'correct_abstention':True}
        self.save_submission()
        result=self.execute()
        self.assertEqual(result['annotations_imported'],2)
        self.assertEqual(result['pending_items'],1)
        receipt=_read(Path(result['reviewer_record']))
        self.assertEqual(receipt['ungraded_items'][0]['reason'],'no_resolved_labels')
        report=_read(Path(result['report']))
        self.assertEqual(report['progress']['overall']['graded'],2)
        self.assertEqual(report['progress']['overall']['ungraded'],1)
        annotations=[json.loads(line) for line in Path(result['annotations']).read_text().splitlines()]
        self.assertEqual({row['correct_abstention'] for row in annotations},{False,True})

    def test_unknown_or_duplicate_item_ids_reject_the_entire_import(self):
        original = deepcopy(self.submission)
        for mode in ('unknown','duplicate'):
            with self.subTest(mode=mode):
                self.submission = deepcopy(original)
                if mode == 'unknown':
                    self.submission['items'][0]['item_id'] = 'invented-id'
                else:
                    self.submission['items'].append(deepcopy(self.submission['items'][0]))
                self.save_submission()
                with self.assertRaises(ValueError):
                    self.execute()
        self.assertFalse((self.directory / 'reviewed_imports').exists())

    def test_answer_question_scope_claim_or_citation_edits_are_rejected(self):
        original = deepcopy(self.submission)
        for field in ('answer','question','source_scope','claims','citation'):
            with self.subTest(field=field):
                self.submission = deepcopy(original)
                item = self.submission['items'][0]
                if field == 'claims':
                    item['claims'][0]['text'] = 'Replacement claim'
                elif field == 'citation':
                    item['claims'][0]['citations'].append(dict(source_id='fake',chunk_id='fake',quote='Fake quote'))
                else:
                    item[field] = 'Replacement text'
                self.save_submission()
                with self.assertRaisesRegex(ValueError, 'Only grading'):
                    self.execute()

    def test_forged_private_mapping_and_changed_prediction_hash_are_rejected(self):
        key_path = self.directory / 'review_key.private.json'
        private = _read(key_path)
        original = deepcopy(private)
        for mode in ('hash','system'):
            with self.subTest(mode=mode):
                private = deepcopy(original)
                private['keys'][0]['prediction_sha256' if mode == 'hash' else 'system'] = 'forged'
                _write(key_path, private)
                with self.assertRaisesRegex(ValueError, 'mapping|hash'):
                    self.execute()

    def test_atomization_does_not_silently_realign_changed_claim_counts(self):
        self.submission['items'][0]['grading']['claims'].append(
            dict(supported=True,citation_valid=False,unsafe_extrapolation=False))
        self.save_submission()
        with self.assertRaisesRegex(ValueError, 'claim count'):
            self.execute()

    def test_uncited_claim_cannot_be_labeled_as_a_valid_citation(self):
        item = next(item for item in self.submission['items'] if not item['claims'][0]['citations'])
        item['grading']['claims'][0]['citation_valid'] = True
        self.save_submission()
        with self.assertRaisesRegex(ValueError, 'uncited claim'):
            self.execute()

    def test_ai_method_missing_qualification_or_missing_human_declaration_reject(self):
        original = deepcopy(self.submission)
        for field,value in (('review_method','ai'),('human_review',False),('independent',False),
                            ('qualification',''),('independence_declaration',''),('reviewed_at','bad-date')):
            with self.subTest(field=field):
                self.submission = dict(deepcopy(original), **{field:value})
                self.save_submission()
                with self.assertRaises(ValueError):
                    self.execute()

    def test_wrong_run_duplicate_json_keys_and_oversized_inputs_reject(self):
        self.submission['benchmark_run_id'] = 'another-run'
        self.save_submission()
        with self.assertRaisesRegex(ValueError, 'another run'):
            self.execute()
        self.path.write_text('{"reviewer":"one","reviewer":"two"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.execute()
        self.path.write_bytes(b'x' * (MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'size limit'):
            self.execute()

    def test_reimport_is_idempotent_and_detects_modified_reviewed_artifacts(self):
        result = self.execute()
        self.assertEqual(self.execute(), result)
        path = Path(result['annotations'])
        path.write_text('forged imported grade\n')
        with self.assertRaisesRegex(ValueError, 'no longer matches'):
            self.execute()

    def test_original_packet_is_not_a_writable_import_target(self):
        with self.assertRaisesRegex(ValueError, 'Review a copy'):
            import_review(self.root, self.run_id, self.directory / 'review_packet.json')


if __name__ == '__main__':
    unittest.main()
