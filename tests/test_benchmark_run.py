"""Exercise benchmark checkpoints and actual research flow with local model fixtures."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.benchmark_run import prepare_review_packet, run_benchmark, benchmark_answers, latest_benchmark
from axiom.model import validate_review


class FixtureModel:
    provider = 'ollama'

    def __init__(self, fixture, name):
        self.fixture = fixture
        self.name = name
        self.calls = []

    def draft(self, question, evidence, baseline=False):
        self.fixture.events.append(('draft', baseline, question, [c['chunk_id'] for c in evidence]))
        if self.fixture.retry:
            self.calls.append({'request_hash': 'synthetic-draft', 'status': 'rate_limited'})
        self.calls.append({'request_hash': 'synthetic-draft', 'status': 'success'})
        if baseline:
            claim = {'text': 'Synthetic baseline response.', 'citations': []}
        else:
            source = evidence[0]
            claim = {'text': source['text'], 'citations': [{'source_id': source['source_id'],
                     'chunk_id': source['chunk_id'], 'quote': source['text']}]}
        return {'claims': [claim], 'abstained': False, 'reason': 'Synthetic generation.'}

    def review(self, claim, evidence):
        self.fixture.events.append(('review', claim))
        if self.fixture.review_fails:
            raise ValueError('Synthetic local review failure')
        source = evidence[0]
        self.calls.append({'request_hash': 'synthetic-review', 'status': 'success'})
        return validate_review({'verdict': 'supported', 'reason': 'Synthetic review.',
                                'uncertainty': 'Synthetic context only.', 'evidence_checks': [{
            'source_id': source['source_id'], 'chunk_id': source['chunk_id'],
            'quote': source['text'], 'relation': 'supports'}]}, evidence)


class BenchmarkRunTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        benchmark = self.root / 'benchmarks'
        benchmark.mkdir()
        self.questions = [{'question_id': 'Q1', 'question': 'What synthetic airflow observations were reported?',
                           'split': 'dev', 'scope': 'Use the named synthetic source.',
                           'rubric': 'Private rubric marker.', 'expected_action': 'Private expected action.'}]
        (benchmark / 'questions.jsonl').write_text(json.dumps(self.questions[0]), encoding='utf-8')
        (benchmark / 'sources.json').write_text('{}', encoding='utf-8')
        self.chunks = [self.chunk('allowed', 'Synthetic airflow observations were reported for the named sample.'),
                       self.chunk('outside', 'Synthetic airflow observations were reported for another source.')]
        self.allowed = ['allowed']
        self.scope_available = True
        self.name = 'synthetic-model'
        self.events = []
        self.retry = False
        self.review_fails = False
        self.original_code_hash = hashlib.sha256((Path(__file__).resolve().parents[1]/'src/axiom/critic.py').read_bytes()).hexdigest()
        self.code_hash = {'critic.py': self.original_code_hash}
        self.replace('load_chunks', side_effect=lambda root: self.chunks)
        self.replace('load_scope_chunks', return_value=[])
        self.replace('load_condition_records', return_value=[])
        self.replace('audit_benchmark', side_effect=self.audit)
        self.factory = self.replace('make_model', side_effect=self.make_model)
        self.replace('_git', return_value={'commit': None, 'working_tree_dirty': None})
        self.replace('_code_hashes', side_effect=lambda: self.code_hash.copy())

    def replace(self, name, **kwargs):
        change = patch('axiom.benchmark_run.' + name, **kwargs)
        self.addCleanup(change.stop)
        return change.start()

    @staticmethod
    def chunk(identifier, text):
        return {'chunk_id': identifier, 'source_id': 'source-' + identifier, 'text': text,
                'sha256': hashlib.sha256(text.encode()).hexdigest(), 'title': 'Synthetic airflow observations',
                'experiment': 'BASS', 'evidence_tier': 2, 'source_kind': 'technical_report',
                'url': 'https://example.invalid/' + identifier, 'locator': 'Fixture page 1', 'conditions': {}}

    def audit(self, root, questions):
        digest = hashlib.sha256(json.dumps(sorted((chunk['chunk_id'], chunk['sha256'])
                                                 for chunk in self.chunks)).encode()).hexdigest()
        return {'corpus_fingerprint': digest, 'counts': {'question_count': len(questions)}, 'questions': [{
            'question_id': q['question_id'], 'all_reference_scopes_available': self.scope_available,
            'allowed_chunk_ids': self.allowed, 'references': [{'url': 'https://example.invalid/allowed',
            'requested_locator': 'Fixture page 1'}], 'readiness': 'candidates_need_review'} for q in questions]}

    def make_model(self, root, provider, model, use_cache):
        return None if provider == 'extractive' else FixtureModel(self, model or self.name)

    def execute(self, systems=('baseline', 'ignis'), **kwargs):
        return run_benchmark(self.root, provider=kwargs.pop('provider', 'ollama'), systems=systems, **kwargs)

    def directory(self, report):
        return self.root / 'runs/benchmarks' / report['benchmark_run_id']

    @staticmethod
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))

    def test_budget_resume_finishes_pending_jobs_without_repeating_completed_call(self):
        updates = []
        first = self.execute(max_jobs=1, progress=updates.append)
        self.assertEqual(first['progress']['overall']['pending'], 1)
        self.assertEqual(first['manifest_status'], 'budget_reached')
        first_job = self.directory(first) / 'jobs/Q1--baseline.json'
        first_bytes = first_job.read_bytes()
        second = self.execute(resume=first['benchmark_run_id'], progress=updates.append)
        self.assertEqual(second['progress']['overall']['completed'], 2)
        self.assertEqual(second['progress']['overall']['graded'], 0)
        self.assertEqual(first_job.read_bytes(), first_bytes)
        self.assertEqual([update['system'] for update in updates], ['baseline', 'ignis'])
        self.assertEqual([event[0] for event in self.events], ['draft', 'draft', 'review'])
        self.execute(resume=first['benchmark_run_id'])
        self.assertEqual(len(self.events), 3)

    def test_changed_corpus_code_model_and_settings_refuse_resume_before_generation(self):
        first = self.execute(max_jobs=1)
        run_id = first['benchmark_run_id']
        original = self.chunks[0]
        self.chunks[0] = self.chunk('allowed', 'Changed source text.')
        with self.assertRaises(ValueError):
            self.execute(resume=run_id)
        self.chunks[0] = original
        self.code_hash['critic.py'] = 'changed-code'
        with self.assertRaises(ValueError):
            self.execute(resume=run_id)
        self.code_hash['critic.py'] = self.original_code_hash
        for settings in ({'model': 'changed-model'}, {'fresh': True}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.execute(resume=run_id, **settings)
        self.assertEqual(len(self.events), 1)

    def test_named_catalog_scope_is_frozen_and_confined_to_requested_chunks(self):
        self.chunks[0].update(source_kind='dataset_catalog', evidence_role='source_description',
                              named_scope_verified=True, section='Objectives',
                              status='active', permission_status='allowed')
        self.replace('load_chunks', return_value=self.chunks[1:])
        self.replace('load_named_chunks', return_value=self.chunks[:1])
        (self.root / 'data').mkdir()
        source_manifest = self.root / 'data/benchmark_sources.json'
        source_manifest.write_text('{"fixture_version": 1}', encoding='utf-8')
        systems = ('rag_only', 'ignis')
        report = self.execute(systems, max_jobs=1)
        directory = self.directory(report)
        manifest = self.read(directory / 'manifest.json')
        self.assertEqual(manifest['inputs']['named_source_manifest_sha256'],
                         hashlib.sha256(source_manifest.read_bytes()).hexdigest())
        self.assertEqual(manifest['inputs']['source_scope_policy']['catalog_role'], 'source_description')
        self.assertEqual(self.events[0][-1], ['allowed'])
        self.assertEqual(self.read(directory / 'corpus_snapshot.json')[-1]['evidence_role'], 'source_description')
        original = (directory / 'jobs/Q1--rag_only.json').read_bytes()
        source_manifest.write_text('{"fixture_version": 2}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Resume refused'):
            self.execute(systems, resume=report['benchmark_run_id'])
        self.assertEqual((directory / 'jobs/Q1--rag_only.json').read_bytes(), original)
        self.assertEqual(len(self.events), 1)

    def test_tampered_manifest_inputs_jobs_or_snapshot_prevent_resume(self):
        first = self.execute(max_jobs=1)
        directory = self.directory(first)
        for filename, mutate in [('manifest.json', lambda data: data['inputs'].update(prompt_version='altered')),
                                 ('manifest.json', lambda data: data['jobs'].clear()),
                                 ('corpus_snapshot.json', lambda data: data[0].update(text='Changed.')),
                                 ('conditions_snapshot.json', lambda data: data.append({'fake': 'condition'}))]:
            path = directory / filename
            content = path.read_bytes()
            with self.subTest(file=filename):
                data = self.read(path)
                mutate(data)
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.execute(resume=first['benchmark_run_id'])
                path.write_bytes(content)
        self.assertEqual(len(self.events), 1)

    def test_missing_and_partially_available_scope_stay_pending_for_both_systems(self):
        for allowed in ([], ['allowed']):
            self.scope_available = False
            self.allowed = allowed
            with self.subTest(allowed=allowed):
                report = self.execute()
                progress = report['progress']['overall']
                self.assertEqual(progress['attempted'], 0)
                self.assertEqual(progress['blocked_scope'], 2)
                self.assertEqual(progress['pending'], 2)
                self.assertEqual(report['manifest_status'], 'pending_source_scope')
                self.assertEqual(self.events, [])

    def test_generation_sees_only_named_source_and_approved_prompt_fields(self):
        self.execute()
        drafts = [event for event in self.events if event[0] == 'draft']
        self.assertEqual([event[3] for event in drafts], [[], ['allowed']])
        self.assertEqual(drafts[0][2], drafts[1][2])
        self.assertIn('Fixture page 1', drafts[0][2])
        self.assertNotIn('Private rubric marker', drafts[0][2])
        self.assertNotIn('Private expected action', drafts[0][2])

    def test_rag_draft_is_shared_with_ignis_in_canonical_order_across_resume(self):
        systems = ['ignis', 'rag_only', 'baseline']
        first = self.execute(systems, max_jobs=2)
        report = self.execute(systems, resume=first['benchmark_run_id'])
        directory = self.directory(report)
        rag = self.read(directory / 'jobs/Q1--rag_only.json')
        ignis = self.read(directory / 'jobs/Q1--ignis.json')
        self.assertEqual([entry[0] for entry in self.events], ['draft', 'draft', 'review'])
        self.assertTrue(self.events[0][1])
        self.assertEqual(ignis['run']['raw_draft'], rag['run']['raw_draft'])
        self.assertEqual(ignis['prediction']['shared_draft_from_run_id'], rag['run']['run_id'])
        self.assertEqual(ignis['prediction']['measurement_scope'], 'incremental_critic_with_shared_rag_draft')
        self.assertEqual(report['progress']['overall']['completed'], 3)

    def test_same_request_retry_then_success_counts_as_completed(self):
        self.retry = True
        report = self.execute(('baseline',))
        self.assertEqual(report['progress']['overall']['failed'], 0)
        self.assertEqual(report['progress']['overall']['completed'], 1)
        self.assertEqual(report['performance']['overall']['model_calls_observed'], 2)

    def test_review_failure_without_transport_error_excluded_from_completed_and_packet(self):
        self.review_fails = True
        report = self.execute(('ignis',))
        progress = report['progress']['overall']
        self.assertEqual(progress['completed'], 0)
        self.assertEqual(progress['failed'], 1)
        self.assertEqual(report['manifest_status'], 'stopped_after_execution_error')
        packet = prepare_review_packet(self.root, report['benchmark_run_id'])
        self.assertEqual(packet['items'], 0)
        self.assertEqual(packet['grades_created'], 0)
        events = self.events[:]
        resumed = self.execute(('ignis',), resume=report['benchmark_run_id'])
        self.assertEqual(resumed['manifest_status'], 'completed_with_errors')
        self.assertEqual(resumed['progress']['overall']['failed'], 1)
        self.assertEqual(self.events, events)

    def test_tampered_nested_record_rejected_by_resume_and_packet(self):
        first = self.execute(max_jobs=1)
        path = self.directory(first) / 'jobs/Q1--baseline.json'
        record = self.read(path)
        record['run']['raw_draft']['claims'][0]['text'] = 'Tampered nested draft.'
        path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.execute(resume=first['benchmark_run_id'])
        with self.assertRaises(ValueError):
            prepare_review_packet(self.root, first['benchmark_run_id'])
        self.assertEqual(len(self.events), 1)

    def test_reading_malformed_jobs_or_report_cannot_escape_or_break_latest_list(self):
        report = self.execute(max_jobs=1)
        directory = self.directory(report)
        path = directory/'manifest.json'
        manifest = self.read(path)
        manifest['jobs'][0]['question_id'] = '../outside'
        path.write_text(json.dumps(manifest),encoding='utf-8')
        with self.assertRaises(ValueError):
            benchmark_answers(self.root, report['benchmark_run_id'])
        path.write_text('[]',encoding='utf-8')
        self.assertIsNone(latest_benchmark(self.root))

    def test_review_packet_blinds_system_and_verdict_without_creating_grades(self):
        report = self.execute()
        output = prepare_review_packet(self.root, report['benchmark_run_id'])
        packet = self.read(Path(output['packet']))
        private = self.read(Path(output['private_key']))
        self.assertEqual(output['items'], 2)
        self.assertEqual(output['grades_created'], 0)
        self.assertEqual({row['system'] for row in private['keys']}, {'baseline', 'ignis'})
        for row in packet['items']:
            self.assertNotIn('system', row)
            self.assertNotIn('question_id', row)
            self.assertIsNone(row['grading'])
            for claim in row['claims']:
                self.assertEqual(set(claim), {'text', 'citations'})
                for citation in claim['citations']:
                    self.assertNotIn('valid', citation)
        self.assertEqual({row['item_id'] for row in packet['items']}, {row['item_id'] for row in private['keys']})
        self.assertEqual(report['progress']['overall']['graded'], 0)

    def test_extractive_has_no_model_baseline_and_executes_real_ignis_excerpt(self):
        for systems in (('baseline',), ('rag_only',), ('baseline', 'ignis')):
            with self.subTest(systems=systems), self.assertRaises(ValueError):
                self.execute(systems, provider='extractive')
        self.factory.assert_not_called()
        report = self.execute(('ignis',), provider='extractive')
        record = self.read(self.directory(report) / 'jobs/Q1--ignis.json')
        self.assertEqual(record['run']['mode'], 'extractive_preview')
        self.assertEqual(record['prediction']['answer'], self.chunks[0]['text'])
        self.assertEqual(record['prediction']['model_calls'], [])
        self.assertEqual(self.events, [])
        self.assertEqual(report['progress']['overall']['completed'], 1)


if __name__ == '__main__':
    unittest.main()
