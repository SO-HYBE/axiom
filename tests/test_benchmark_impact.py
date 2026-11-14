"""Observed comparison accounting; synthetic cases, never scientific grades."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from axiom.benchmark_impact import summarize_impact
from axiom.benchmark_run import _read, _write
import test_benchmark_inspect as fixtures


class BenchmarkImpactTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BenchmarkInspectTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.run_id = self.fixture.root, self.fixture.run_id
        # Normalize the inspector fixture to the actual RAG/critic contracts.
        rag = self.fixture.records['rag_only']
        rag['run']['claims'] = [dict(deepcopy(c),verdict='unfiltered') for c in self.fixture.raw['claims']]
        rag['prediction']['claims'] = deepcopy(rag['run']['claims'])
        ignis = self.fixture.records['ignis']
        ignis['run']['claims'] = deepcopy(ignis['run']['draft_checks'])
        ignis['prediction']['claims'] = deepcopy(ignis['run']['claims'])
        self.save()

    def save(self):
        for system in self.fixture.records:
            self.fixture.save_record(system)
        self.fixture.checkpoint()

    def summary(self):
        with patch('axiom.providers.make_model',side_effect=AssertionError('Metrics must not call models')), \
             patch('axiom.benchmark_run.make_model',side_effect=AssertionError('Metrics must stay offline')):
            return summarize_impact(self.root,self.run_id)

    def test_shared_pair_counts_claims_but_does_not_claim_scientific_accuracy(self):
        value = self.summary()
        self.assertTrue(value['integrity_verified'])
        self.assertEqual(value['critic']['matched_pairs'],1)
        self.assertEqual(value['critic']['rag_output_claims'],1)
        self.assertEqual(value['critic']['ignis_output_claims'],1)
        self.assertEqual(value['critic']['additional_withheld_claims'],0)
        self.assertEqual(value['scientific_quality']['independent_grades'],0)
        self.assertIsNone(value['scientific_quality']['accuracy'])
        self.assertEqual(value['questions'][0]['pair_status'],'matched')

    def test_additional_withholding_and_overlapping_reasons_use_released_rag_denominator(self):
        ignis = self.fixture.records['ignis']
        check = ignis['run']['draft_checks'][0]
        check.update(verdict='needs_review',issues=['target_conditions_incomplete','operational_inference_requires_expert_review'])
        for row in (ignis['run'],ignis['prediction']):
            row.update(claims=[],abstained=True)
        self.save()
        value = self.summary()['critic']
        self.assertEqual(value['additional_withheld_rate'],dict(numerator=1,denominator=1,value=1.0))
        reasons = {row['id']:row['claims'] for row in value['reasons']}
        self.assertEqual(reasons['conditions'],1)
        self.assertEqual(reasons['applicability'],1)
        self.assertGreater(sum(reasons.values()),value['additional_withheld_claims'])
        transition = next(row for row in value['answer_transitions'] if row['source']=='answered' and row['target']=='abstained')
        self.assertEqual(transition['count'],1)

    def test_writer_abstained_raw_claims_are_not_critic_removals(self):
        for system in ('rag_only','ignis'):
            record = self.fixture.records[system]
            record['run']['raw_draft']['abstained'] = True
            for row in (record['run'],record['prediction']):
                row.update(claims=[],abstained=True)
        self.save()
        value = self.summary()['critic']
        self.assertEqual(value['raw_draft_claims'],1)
        self.assertEqual(value['writer_withheld_claims'],1)
        self.assertEqual(value['rag_output_claims'],0)
        self.assertEqual(value['additional_withheld_claims'],0)
        self.assertIsNone(value['additional_withheld_rate']['value'])
        self.assertTrue(all(row['claims']==0 for row in value['reasons']))

    def test_failed_review_is_excluded_not_counted_as_a_successful_abstention(self):
        ignis = self.fixture.records['ignis']
        for row in (ignis['run'],ignis['prediction']):
            row.update(claims=[],abstained=True)
        ignis['prediction']['execution_error']='Synthetic provider failed.'
        self.save()
        value = self.summary()
        self.assertEqual(value['critic']['matched_pairs'],0)
        self.assertEqual(value['critic']['excluded_pairs'],1)
        self.assertEqual(value['critic']['additional_withheld_claims'],0)
        row = next(item for item in value['systems'] if item['system']=='ignis')
        self.assertEqual((row['failed'],row['abstained'],row['completed']),(1,0,0))
        self.assertIsNone(value['questions'][0]['systems']['ignis']['claims'])

    def test_pending_execution_is_not_a_zero_effect_case(self):
        (self.fixture.directory/'jobs/Q001--ignis.json').unlink()
        self.fixture.checkpoint()
        value = self.summary()
        self.assertFalse(value['critic']['available'])
        self.assertEqual(value['critic']['exclusions'][0]['reason'],'pair_pending')
        self.assertIsNone(value['questions'][0]['additional_withheld_claims'])

    def test_tampered_digest_and_changed_pair_fail_closed(self):
        path = self.fixture.directory/'jobs/Q001--ignis.json'
        value = _read(path);value['run']['raw_draft']['reason']='Synthetic tamper.';_write(path,value)
        with self.assertRaises(ValueError):self.summary()
        self.fixture.records['ignis']['run']['raw_draft']['reason']='Different synthetic draft.'
        self.save()
        with self.assertRaises(ValueError):self.summary()

    def test_summary_reads_do_not_mutate_saved_records_or_create_scores(self):
        paths = [p for p in self.fixture.directory.rglob('*') if p.is_file() and p.name!='.write.lock']
        before = {str(p):p.read_bytes() for p in paths}
        self.summary();self.summary()
        self.assertEqual(before,{str(p):p.read_bytes() for p in paths})
        self.assertFalse((self.fixture.directory/'reviewed_imports').exists())

    def test_provider_events_distinguish_cache_fresh_success_and_retry(self):
        self.fixture.records['baseline']['run']['model_calls']=[{'status':'cache_hit','cache_hit':True},{'status':'rate_limited'},{'status':'success','cache_hit':False}]
        self.save()
        value = self.summary()['provider']
        self.assertEqual(value['cache_hits'],1)
        self.assertEqual(value['fresh_successes'],1)
        self.assertEqual(value['statuses']['rate_limited'],1)

