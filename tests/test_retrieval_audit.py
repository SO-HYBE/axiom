from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.benchmark_run import _hash, _write
from axiom.retrieval_audit import audit_retrieval


class RetrievalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'runs/benchmarks/synthetic-retrieval'
        self.directory.mkdir(parents=True)
        self.chunks = [self.chunk('named', 'Synthetic droplet research objective.'),
                       self.chunk('outside', 'Secret rubric lunar claims and unsupported measurement values.')]
        self.question = dict(question_id='Q001', question='What do the droplet objectives establish about every lunar fuel measurement?',
                             expected_action='SECRET EXPECTED LABEL', rubric='SECRET RUBRIC', category='answerable')
        self.scope = dict(question_id='Q001', all_reference_scopes_available=True,
                          allowed_chunk_ids=['named'], references=[{'mapped_source_ids':['named-source']}], warnings=[])
        self.write()

    def chunk(self, identifier, text, **updates):
        value = dict(chunk_id=identifier, source_id='named-source' if identifier == 'named' else 'outside-source',
                     text=text, sha256=hashlib.sha256(text.encode()).hexdigest(), title='Synthetic source',
                     experiment='Synthetic', source_kind='technical_report', locator='Objectives',
                     evidence_tier=2, permission_status='allowed', status='active', conditions={})
        value.update(updates)
        return value

    def write(self):
        self.inputs = dict(questions=[self.question], scope_plan=[self.scope], corpus_sha256=_hash(self.chunks),
                           code_sha256={'retrieval.py':'synthetic-frozen-code'})
        self.manifest = dict(run_id='synthetic-retrieval', inputs=self.inputs, input_fingerprint=_hash(self.inputs))
        _write(self.directory / 'manifest.json', self.manifest)
        _write(self.directory / 'corpus_snapshot.json', self.chunks)

    def inspect(self):
        with patch('axiom.benchmark_run.make_model', side_effect=AssertionError('No models')):
            return audit_retrieval(self.root, 'synthetic-retrieval')

    def test_only_scoped_passages_are_diagnosed_and_no_files_change(self):
        before = {str(path):path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result = self.inspect()
        after = {str(path):path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        row = result['questions'][0]
        self.assertEqual(row['status'], 'below_lexical_threshold')
        self.assertEqual(row['allowed_passage_count'], 1)
        self.assertEqual([item['chunk_id'] for item in row['diagnostic_below_threshold']], ['named'])
        self.assertNotIn('outside', json.dumps(row))
        self.assertTrue(row['finite_named_scope_fits_context'])
        self.assertEqual(result['scientific_grades_created'], 0)
        self.assertIsNone(row['scientific_support'])

    def test_labels_and_rubrics_never_enter_the_query_or_output(self):
        from axiom.retrieval import search
        with patch('axiom.retrieval.search', wraps=search) as recorded:
            first = self.inspect()
        self.assertTrue(all(call.args[0] == self.question['question'] for call in recorded.call_args_list))
        self.assertNotIn('SECRET', json.dumps(first))
        self.question.update(expected_action='DIFFERENT LABEL', rubric='DIFFERENT RUBRIC', category='trap')
        self.write()
        second = self.inspect()
        # Fingerprint changes because the frozen file is different, but diagnostics do not.
        self.assertEqual(first['questions'], second['questions'])

    def test_missing_scope_never_searches_global_or_even_present_allowed_passages(self):
        self.scope['all_reference_scopes_available'] = False
        self.write()
        row = self.inspect()['questions'][0]
        self.assertEqual(row['status'], 'source_scope_unavailable')
        self.assertEqual(row['scoped_passage_diagnostics'], [])
        self.assertFalse(row['finite_named_scope_fits_context'])

    def test_zero_overlap_remains_zero_and_is_not_approved_context(self):
        self.question['question'] = 'Hypothetical zebra habitat certification?'
        self.write()
        row = self.inspect()['questions'][0]
        self.assertEqual(row['status'], 'zero_lexical_overlap')
        self.assertEqual(row['diagnostic_below_threshold'], [])
        self.assertTrue(row['finite_named_scope_fits_context'])
        self.assertFalse(row['generation_policy_changed'])

    def test_unscoped_global_pool_is_not_finite_named_context(self):
        self.scope['references'] = []
        self.write()
        self.assertFalse(self.inspect()['questions'][0]['finite_named_scope_fits_context'])

    def test_body_and_metadata_matches_remain_distinguishable(self):
        self.question['question'] = 'What synthetic objectives define the droplet investigation?'
        self.write()
        row = self.inspect()['questions'][0]['scoped_passage_diagnostics'][0]
        self.assertIn('droplet', row['body_matched_terms'])
        self.assertIn('objectives', row['locator_matched_terms'])
        self.assertNotIn('objectives', row['body_matched_terms'])

    def test_ligature_normalization_is_only_a_separate_diagnostic(self):
        self.chunks[0] = self.chunk('named', 'Synthetic \ufb01re behavior.')
        self.question['question'] = 'What fire behavior is reported?'
        self.write()
        row = self.inspect()['questions'][0]['scoped_passage_diagnostics'][0]
        self.assertNotIn('fire', row['body_matched_terms'])
        self.assertIn('fire', row['nfkc_body_matched_terms'])

    def test_context_budget_is_not_bypassed(self):
        self.chunks[0] = self.chunk('named', 'Synthetic droplet ' * 900)
        self.write()
        self.assertFalse(self.inspect()['questions'][0]['finite_named_scope_fits_context'])

    def test_permission_hold_does_not_enter_diagnostics_or_context_feasibility(self):
        self.chunks[0]['permission_status'] = 'hold'
        self.write()
        row = self.inspect()['questions'][0]
        self.assertEqual(row['eligible_passage_count'], 0)
        self.assertEqual(row['excluded_passage_ids'], ['named'])
        self.assertEqual(row['scoped_passage_diagnostics'], [])
        self.assertFalse(row['finite_named_scope_fits_context'])

    def test_tampered_corpus_or_input_is_rejected(self):
        path = self.directory / 'corpus_snapshot.json'
        original = path.read_bytes()
        path.write_text('[]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'corpus'):
            self.inspect()
        path.write_bytes(original)
        self.manifest['inputs']['questions'][0]['question'] = 'Changed query'
        _write(self.directory / 'manifest.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            self.inspect()

    def test_unknown_duplicate_or_malformed_boundaries_fail_closed(self):
        for allowed in (['unknown'], ['named','named'], [42]):
            with self.subTest(allowed=allowed):
                self.scope['allowed_chunk_ids'] = allowed
                self.write()
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_diagnostics_are_deterministic_and_bounds_are_checked(self):
        self.assertEqual(self.inspect(), self.inspect())
        for value in (True, 0, 11):
            with self.assertRaises(ValueError):
                audit_retrieval(self.root, 'synthetic-retrieval', candidate_limit=value)


if __name__ == '__main__':
    unittest.main()
