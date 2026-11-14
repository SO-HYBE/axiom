"""Controlled comparison behavior with synthetic models; no provider traffic."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.comparison import compare, validate_request
from axiom.research import run
from axiom.run_records import load_comparison, load_run
from test_research import corpus


class FixtureModel:
    provider = 'groq'
    name = 'fixture-fixed-model'

    def __init__(self):
        self.calls = []
        self.inputs = []

    def draft(self, question, evidence, baseline=False):
        self.inputs.append((question, deepcopy(evidence), baseline))
        self.calls.append({'cache_hit': False})
        return {'claims': [{'text': corpus()[0]['text'], 'citations': [] if baseline else [
            {'source_id': 'nasa-1', 'chunk_id': 'c1', 'quote': corpus()[0]['text']}]}],
            'abstained': False, 'reason': 'Synthetic fixture'}

    def review(self, claim, evidence):
        return {'verdict': 'supported', 'reason': 'Synthetic review'}


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.models = [FixtureModel(), FixtureModel()]
        self.factory = patch('axiom.comparison.make_model', side_effect=self.models).start()
        self.addCleanup(patch.stopall)
        self.chunks = corpus()
        patch('axiom.comparison.load_chunks', return_value=self.chunks).start()
        patch('axiom.comparison.load_condition_records', return_value=[]).start()
        self.request = {'question': 'What did BASS-II investigate about airflow?', 'provider': 'groq'}

    def test_same_question_and_resolved_model_with_different_evidence_access(self):
        pair = compare(self.root, self.request)
        self.assertEqual(pair['status'], 'complete')
        self.assertEqual(self.factory.call_args_list[1].args[2], 'fixture-fixed-model')
        baseline, ignis = (model.inputs[0] for model in self.models)
        self.assertEqual(baseline[0], ignis[0])
        self.assertEqual(baseline[1], [])
        self.assertTrue(ignis[1])
        self.assertTrue(baseline[2])
        self.assertFalse(ignis[2])
        self.assertEqual(pair['baseline']['evidence'], [])
        self.assertEqual(load_comparison(self.root, pair['comparison_id']), pair)
        for side in ('baseline', 'ignis'):
            self.assertEqual(load_run(self.root, pair[side]['run_id']), pair[side])

    def test_target_is_equal_unverified_input_to_both_writers(self):
        target = {'gravity': 'microgravity', 'oxygen_percent': 21}
        request = dict(self.request, target=target, intent='applicability')
        before = deepcopy(request)
        pair = compare(self.root, request)
        a, b = [model.inputs[0][0] for model in self.models]
        self.assertEqual(a, b)
        self.assertIn('unverified input', a)
        self.assertIn('"oxygen_percent": 21', a)
        self.assertEqual(pair['question'], request['question'])
        self.assertEqual(request, before)

    def test_default_can_reuse_cache_and_fresh_disables_it_on_both_sides(self):
        compare(self.root, dict(self.request, fresh=True))
        self.assertTrue(all(call.kwargs['use_cache'] is False for call in self.factory.call_args_list))

    def test_filters_apply_only_to_ignis_and_inputs_are_frozen(self):
        records = [{'record_id': 'synthetic'}]
        patch('axiom.comparison.load_condition_records', return_value=records).start()
        seen = []
        def runner(question, chunks, **kwargs):
            seen.append((chunks, deepcopy(kwargs)))
            if kwargs['system'] == 'baseline':
                # Simulate an on-disk reload changing after the first answer.
                self.chunks.clear()
                records.clear()
            return {'run_id': kwargs['system'], 'answer': 'Fixture answer', 'system': kwargs['system']}
        with patch('axiom.comparison.run', side_effect=runner):
            compare(self.root, dict(self.request, experiments=['BASS-II'], source_ids=['nasa-1'], include_overviews=True))
        self.assertEqual(seen[0][0], [])
        self.assertIsNone(seen[0][1]['experiments'])
        self.assertEqual(seen[0][1]['condition_records'], [])
        self.assertEqual(len(seen[1][0]), 1)
        self.assertEqual(seen[1][1]['condition_records'], [{'record_id': 'synthetic'}])
        self.assertEqual(seen[1][1]['source_ids'], ['nasa-1'])

    def test_model_mismatch_rejected_before_either_writer(self):
        self.models[1].name = 'different'
        with self.assertRaisesRegex(ValueError, 'different IDs'):
            compare(self.root, self.request)
        self.assertFalse(any(model.inputs for model in self.models))

    def test_extractive_comparison_is_not_a_fake_baseline(self):
        with self.assertRaises(ValueError):
            compare(self.root, dict(self.request, provider='extractive'))
        self.factory.assert_not_called()

    def test_one_execution_failure_keeps_and_saves_other_answer(self):
        def runner(question, chunks, **kwargs):
            if kwargs['system'] == 'baseline':
                raise RuntimeError('private error text must not leak')
            return run(question, chunks, **kwargs)
        with patch('axiom.comparison.run', side_effect=runner):
            pair = compare(self.root, self.request)
        self.assertEqual(pair['status'], 'partial')
        self.assertTrue(pair['ignis']['answer'])
        self.assertEqual(pair['baseline']['answer_status'], 'execution_error')
        self.assertNotIn('private error', str(pair))
        self.assertEqual(load_comparison(self.root, pair['comparison_id']), pair)

    def test_both_failed_executions_and_honest_abstention_are_distinct(self):
        with patch('axiom.comparison.run', side_effect=RuntimeError('fixture')):
            pair = compare(self.root, self.request)
        self.assertEqual(pair['status'], 'failed')
        self.assertEqual(set(pair['errors']), {'baseline', 'ignis'})

    def test_insufficient_evidence_is_a_completed_comparison(self):
        pair = compare(self.root, dict(self.request, question='Banana cryptocurrency valuation'))
        self.assertEqual(pair['status'], 'complete')
        self.assertTrue(pair['ignis']['abstained'])
        self.assertEqual(self.models[1].inputs, [])

    def test_run_storage_failure_does_not_discard_response_or_pair(self):
        with patch('axiom.comparison.save_run', side_effect=OSError('fixture disk failure')):
            pair = compare(self.root, self.request)
        self.assertEqual(pair['status'], 'partial')
        self.assertTrue(pair['baseline']['answer'])
        self.assertFalse(pair['saved_locally'])
        self.assertEqual(set(pair['errors']), {'baseline_save', 'ignis_save'})
        self.assertEqual(load_comparison(self.root, pair['comparison_id']), pair)

    def test_pair_storage_failure_is_visible_and_exportable(self):
        with patch('axiom.comparison.save_comparison', side_effect=ValueError('fixture bounds')):
            pair = compare(self.root, self.request)
        self.assertFalse(pair['saved_locally'])
        self.assertIn('comparison_save', pair['errors'])
        self.assertEqual(pair['status'], 'partial')
        self.assertTrue(pair['ignis']['answer'])

    def test_invalid_controls_fail_before_model_preparation(self):
        for invalid in ({'question': ''}, {'fresh': 'false'}, {'target': []},
                        {'include_overviews': 1}, {'source_ids': 'all'}, {'provider': 'paid-fallback'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                compare(self.root, dict(self.request, **invalid))
        self.factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
