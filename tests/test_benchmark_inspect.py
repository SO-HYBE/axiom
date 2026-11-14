"""Synthetic saved-run audits; no scientific labels, models or network calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from axiom.benchmark_inspect import inspect_benchmark
from axiom.benchmark_run import _checkpoint, _directory, _hash, _read, _write


class BenchmarkInspectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_id = 'synthetic-phase6c'
        self.directory = _directory(self.root, self.run_id)
        self.directory.mkdir(parents=True)
        self.text = 'Synthetic named-source objective, not a measured result.'
        self.chunk = dict(chunk_id='allowed-chunk', source_id='synthetic-source',
                          text=self.text, sha256=hashlib.sha256(self.text.encode()).hexdigest(),
                          conditions={}, locator='Synthetic Objectives', url='https://example.invalid/source')
        code = b'# Synthetic frozen code snapshot.\n'
        inputs = {
            'systems': ['baseline', 'rag_only', 'ignis'],
            'questions': [{'question_id': 'Q001', 'question': 'What is the synthetic objective?', 'split': 'dev'}],
            'scope_plan': [{'question_id': 'Q001', 'allowed_chunk_ids': ['allowed-chunk'],
                            'all_reference_scopes_available': True}],
            'corpus_sha256': _hash([self.chunk]), 'condition_sha256': _hash([]),
            'code_sha256': {'critic.py': hashlib.sha256(code).hexdigest()},
            'provider': 'synthetic', 'model': 'synthetic-model',
        }
        jobs = [dict(question_id='Q001', system=system, split='dev', block_reason=None)
                for system in inputs['systems']]
        self.manifest = dict(schema_version='1.0', run_id=self.run_id, status='complete',
                             evaluation_kind='exploratory_model_generation',
                             annotation_status='unreviewed_no_scientific_scores',
                             is_scientific_validation=False, inputs=inputs,
                             input_fingerprint=_hash(inputs), jobs=jobs)
        _write(self.directory / 'corpus_snapshot.json', [self.chunk])
        _write(self.directory / 'conditions_snapshot.json', [])
        snapshot = self.directory / 'code_snapshot'
        snapshot.mkdir()
        (snapshot / 'critic.py').write_bytes(code)
        raw_claim = dict(text=self.text, citations=[dict(source_id='synthetic-source',
                         chunk_id='allowed-chunk', quote=self.text)])
        self.raw = dict(claims=[raw_claim], abstained=False, reason='Synthetic response.')
        self.records = {}
        for system in inputs['systems']:
            claim = deepcopy(raw_claim)
            claim['verdict'] = 'model_supported_needs_review' if system == 'ignis' else 'unreviewed'
            if system == 'baseline':
                claim['citations'] = []
            latency = {'baseline': 50, 'rag_only': 100, 'ignis': 25}[system]
            run = dict(run_id='synthetic-' + system, system=system, question=inputs['questions'][0]['question'],
                       raw_draft=deepcopy(self.raw), evidence=[] if system == 'baseline' else [deepcopy(self.chunk)],
                       claims=[deepcopy(claim)], draft_checks=[dict(deepcopy(claim), issues=[])] if system == 'ignis' else [],
                       abstained=False, answer=self.text, applicability_requested=False,
                       latency_ms=latency, model_calls=[],
                       model_info={'provider': 'synthetic', 'model': 'synthetic-model'})
            prediction = dict(question_id='Q001', system=system, split='dev', run_id=run['run_id'],
                              answer=self.text, abstained=False, claims=[deepcopy(claim)],
                              latency_ms=latency, model_calls=[], policy_withholding=False,
                              measurement_scope='incremental_critic_with_shared_rag_draft' if system == 'ignis' else 'whole_workflow')
            if system == 'ignis':
                prediction['shared_draft_from_run_id'] = 'synthetic-rag_only'
            record = dict(question_id='Q001', system=system,
                          input_fingerprint=self.manifest['input_fingerprint'],
                          generation_scope='Synthetic named source only.', run=run, prediction=prediction,
                          shared_draft_from_run_id='synthetic-rag_only' if system == 'ignis' else None)
            self.records[system] = record
            self.save_record(system)
        self.checkpoint()

    def save_record(self, system):
        record = deepcopy(self.records[system])
        record['record_sha256'] = _hash(record)
        _write(self.directory / 'jobs' / ('Q001--' + system + '.json'), record)

    def checkpoint(self):
        _checkpoint(self.directory, self.manifest)

    def inspect(self):
        with patch('axiom.benchmark_run.make_model', side_effect=AssertionError('Must remain offline')):
            return inspect_benchmark(self.root, self.run_id)

    @staticmethod
    def codes(result):
        return {issue['code'] for issue in result['issues']}

    def test_complete_pair_passes_and_never_converts_verdicts_into_grades(self):
        result = self.inspect()
        self.assertTrue(result['audit_passed'], result['issues'])
        self.assertEqual(result['independent_grades'], 0)
        self.assertEqual(result['progress']['overall']['completed'], 3)
        self.assertEqual(result['progress']['overall']['graded'], 0)
        self.assertEqual(result['pairs'][0]['whole_workflow_latency_ms'], 125)

    def test_changed_frozen_snapshots_fail_audit(self):
        for filename, blob, code in [
            ('corpus_snapshot.json', b'[]', 'corpus_snapshot_mismatch'),
            ('conditions_snapshot.json', b'[{}]', 'conditions_snapshot_mismatch'),
            ('code_snapshot/critic.py', b'# Altered code.\n', 'code_snapshot_mismatch'),
        ]:
            path = self.directory / filename
            original = path.read_bytes()
            try:
                with self.subTest(filename=filename):
                    path.write_bytes(blob)
                    result = self.inspect()
                    self.assertFalse(result['audit_passed'])
                    self.assertIn(code, self.codes(result))
            finally:
                path.write_bytes(original)

    def test_corrupt_job_digest_is_rejected_before_trusting_records(self):
        path = self.directory / 'jobs/Q001--ignis.json'
        record = _read(path)
        record['run']['raw_draft']['reason'] = 'Tampered without digest update.'
        _write(path, record)
        with self.assertRaises(ValueError):
            self.inspect()

    def test_baseline_receiving_corpus_context_is_a_protocol_failure(self):
        self.records['baseline']['run']['evidence'] = [deepcopy(self.chunk)]
        self.save_record('baseline')
        self.checkpoint()
        result = self.inspect()
        self.assertFalse(result['audit_passed'])
        self.assertIn('baseline_evidence_leak', self.codes(result))

    def test_retrieved_evidence_outside_the_allowed_scope_fails(self):
        self.records['rag_only']['run']['evidence'][0]['chunk_id'] = 'outside-chunk'
        self.save_record('rag_only')
        self.checkpoint()
        result = self.inspect()
        self.assertFalse(result['audit_passed'])
        self.assertIn('evidence_outside_scope', self.codes(result))

    def test_distinct_draft_or_wrong_draft_link_fails_pair_integrity(self):
        original = deepcopy(self.records['ignis'])
        for case in ('draft', 'link'):
            with self.subTest(case=case):
                self.records['ignis'] = deepcopy(original)
                if case == 'draft':
                    self.records['ignis']['run']['raw_draft']['reason'] = 'Different draft.'
                    expected = 'shared_draft_mismatch'
                else:
                    self.records['ignis']['shared_draft_from_run_id'] = 'wrong-rag-run'
                    expected = 'shared_draft_link_mismatch'
                self.save_record('ignis')
                self.checkpoint()
                result = self.inspect()
                self.assertFalse(result['audit_passed'])
                self.assertIn(expected, self.codes(result))

    def test_an_incomplete_pair_keeps_workflow_timing_unknown(self):
        (self.directory / 'jobs/Q001--ignis.json').unlink()
        self.manifest['status'] = 'budget_reached'
        self.checkpoint()
        result = self.inspect()
        self.assertTrue(result['audit_passed'], result['issues'])
        self.assertEqual(result['progress']['overall']['pending'], 1)
        self.assertIsNone(result['pairs'][0]['whole_workflow_latency_ms'])

    def test_evidence_abstentions_and_unavailable_source_are_not_grades_or_failures(self):
        raw = dict(claims=[], abstained=True, reason='No matching synthetic evidence.')
        for system in ('rag_only', 'ignis'):
            record = self.records[system]
            record['run'].update(raw_draft=deepcopy(raw), evidence=[], claims=[], draft_checks=[],
                                 abstained=True, answer=raw['reason'])
            record['prediction'].update(claims=[], abstained=True, answer=raw['reason'])
            self.save_record(system)
        inputs = self.manifest['inputs']
        inputs['questions'].append(dict(question_id='Q026', question='Synthetic missing source?', split='test'))
        inputs['scope_plan'].append(dict(question_id='Q026', allowed_chunk_ids=[],
                                          all_reference_scopes_available=False))
        for system in inputs['systems']:
            self.manifest['jobs'].append(dict(question_id='Q026', system=system, split='test',
                                              block_reason='named_scope_unavailable'))
        self.manifest['input_fingerprint'] = _hash(inputs)
        self.manifest['status'] = 'pending_source_scope'
        for system in inputs['systems']:
            self.records[system]['input_fingerprint'] = self.manifest['input_fingerprint']
            self.save_record(system)
        self.checkpoint()
        result = self.inspect()
        self.assertTrue(result['audit_passed'], result['issues'])
        counts = result['progress']['overall']
        self.assertEqual((counts['scheduled'], counts['completed'], counts['failed'], counts['pending']), (6, 3, 0, 3))
        self.assertEqual(counts['blocked_scope'], 3)
        self.assertEqual(result['independent_grades'], 0)

    def test_saved_progress_disagreement_is_detected(self):
        path = self.directory / 'report.json'
        report = _read(path)
        report['progress']['overall']['completed'] = 100
        _write(path, report)
        result = self.inspect()
        self.assertFalse(result['audit_passed'])
        self.assertIn('progress_mismatch', self.codes(result))

    def test_execution_of_a_source_blocked_job_is_a_protocol_failure(self):
        self.manifest['jobs'][0]['block_reason'] = 'named_scope_unavailable'
        self.checkpoint()
        result = self.inspect()
        self.assertFalse(result['audit_passed'])
        self.assertIn('executed_blocked_source', self.codes(result))

    def test_healthy_record_must_match_frozen_model_provider_and_run_system(self):
        original = deepcopy(self.records['baseline'])
        for field in ('model', 'provider', 'system'):
            with self.subTest(field=field):
                self.records['baseline'] = deepcopy(original)
                run = self.records['baseline']['run']
                if field == 'system':
                    run['system'] = 'ignis'
                    expected = 'run_system_mismatch'
                else:
                    run['model_info'][field] = 'a-different-' + field
                    expected = 'model_identity_mismatch'
                self.save_record('baseline')
                self.checkpoint()
                result = self.inspect()
                self.assertFalse(result['audit_passed'])
                self.assertIn(expected, self.codes(result))

    def test_prediction_must_preserve_recorded_answer_claims_and_abstention(self):
        original = deepcopy(self.records['baseline'])
        for field in ('answer', 'claims', 'abstained'):
            with self.subTest(field=field):
                self.records['baseline'] = deepcopy(original)
                prediction = self.records['baseline']['prediction']
                if field == 'answer':
                    prediction['answer'] = 'Replaced exported answer.'
                elif field == 'claims':
                    prediction['claims'] = []
                else:
                    prediction['abstained'] = True
                self.save_record('baseline')
                self.checkpoint()
                result = self.inspect()
                self.assertFalse(result['audit_passed'])
                self.assertIn('prediction_run_mismatch', self.codes(result))

    def test_only_ignis_applicability_flag_counts_as_policy_withholding(self):
        for system in self.records:
            self.records[system]['prediction']['policy_withholding'] = True
            self.save_record(system)
        self.checkpoint()
        result = self.inspect()
        self.assertIsNone(result['by_system']['baseline']['policy_withholding'])
        self.assertIsNone(result['by_system']['rag_only']['policy_withholding'])
        self.assertEqual(result['by_system']['ignis']['policy_withholding'], 1)

    def test_inspection_needs_no_write_access_to_a_deployment_snapshot(self):
        """A read-only bundle (serverless deployment) must still be inspectable."""
        (self.directory / '.write.lock').write_bytes(b'0')
        original = Path.open
        attempts = []
        def guarded(path, mode='r', *args, **kwargs):
            if Path(path).is_relative_to(self.directory) and set(mode) & set('wax+'):
                attempts.append((Path(path).name, mode))
                raise PermissionError(30, 'Read-only file system')
            return original(path, mode, *args, **kwargs)
        # Emulate the POSIX read-lock branch, which is what a container uses.
        fake_fcntl = types.SimpleNamespace(flock=lambda *args: None, LOCK_EX=2, LOCK_NB=4, LOCK_UN=8)
        with patch('pathlib.Path.open', guarded), \
                patch('axiom.review.os', types.SimpleNamespace(name='posix', SEEK_END=2)), \
                patch.dict(sys.modules, {'fcntl': fake_fcntl}):
            result = self.inspect()
        self.assertEqual(attempts, [])
        self.assertTrue(result['audit_passed'], result['issues'])

    def test_error_stub_does_not_require_healthy_run_model_or_system_metadata(self):
        record = self.records['baseline']
        record['run'] = dict(run_id='synthetic-baseline', answer='', abstained=True,
                             claims=[], model_calls=[], latency_ms=1,
                             error='Synthetic execution failure.')
        record['prediction'].update(answer='', abstained=True, claims=[], latency_ms=1,
                                     execution_error='Synthetic execution failure.')
        self.save_record('baseline')
        self.manifest['status'] = 'completed_with_errors'
        self.checkpoint()
        result = self.inspect()
        self.assertTrue(result['audit_passed'], result['issues'])
        self.assertEqual(result['progress']['overall']['failed'], 1)
        self.assertEqual(result['progress']['overall']['completed'], 2)
        self.assertNotIn('model_identity_mismatch', self.codes(result))
        self.assertNotIn('run_system_mismatch', self.codes(result))


if __name__ == '__main__':
    unittest.main()
