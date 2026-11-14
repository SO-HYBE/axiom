import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from axiom.server import make_handler
from axiom.run_records import save_run, save_comparison
from test_research import corpus


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.root = root
        (root / "data/processed").mkdir(parents=True)
        (root / "data/processed/chunks.jsonl").write_text(json.dumps(corpus()[0]))
        (root / "data/sources.json").write_text('{"sources": []}')
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_http_end_to_end(self):
        with self.opener.open(self.url + "/") as r:
            self.assertIn(b"AXIOM", r.read())
        req = urllib.request.Request(self.url + "/api/ask", json.dumps({"question": "BASS-II airflow"}).encode(), {"Content-Type": "application/json"})
        with self.opener.open(req) as r:
            result = json.load(r)
        self.assertEqual(result["mode"], "extractive_preview")
        self.assertTrue(result["claims"])

    def test_cross_origin_blocked(self):
        req = urllib.request.Request(self.url + "/api/ask", b'{}', {"Content-Type": "application/json", "Origin": "https://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.opener.open(req)
        self.assertEqual(raised.exception.code, 403)

    def test_conditions_endpoint_with_no_drafts(self):
        with self.opener.open(self.url + "/api/conditions") as response:
            data=json.load(response)
        self.assertEqual(data["records"], [])
        self.assertEqual(data["validation"]["valid_count"],0)
        self.assertEqual(data["coverage"]["human_reviewed_condition_records"],0)

    def test_official_resource_endpoint_reports_all_ten_and_unknown_acquisitions(self):
        source = Path(__file__).resolve().parents[1] / 'data/official_resources.json'
        (self.root / 'data/official_resources.json').write_bytes(source.read_bytes())
        report = self.get_json('/api/resources')
        self.assertEqual(report['resource_count'], 10)
        self.assertEqual(report['resources'][0]['resource_id'], 'R1')
        self.assertEqual(report['raw_experimental_file_count'], 0)
        self.assertEqual(report['resources'][1]['acquisition_status'], 'not_acquired')

    def test_axiom_result_and_trace_demo_endpoints(self):
        self.assertEqual(self.get_json('/api/axiom/evaluation'),
                         {'status': 'not_run', 'results': None})
        result_path = self.root / 'runs/axiom/evaluation/results.json'
        result_path.parent.mkdir(parents=True)
        result_path.write_text(json.dumps({'commit': 'fixture', 'dataset': {'questions': 36}}),
                               encoding='utf-8')
        self.assertEqual(self.get_json('/api/axiom/evaluation')['results']['commit'], 'fixture')

        jobs = self.root / 'runs/benchmarks/3c3cc0f1e4b949a8a33296e94417f13c/jobs'
        jobs.mkdir(parents=True)
        run = {'run_id': 'fixture-run', 'system': 'ignis', 'question': 'fixture',
               'abstained': False, 'evidence': [{'chunk_id': 'e1', 'conditions': {}}],
               'target': {}, 'applicability_requested': True,
               'claims': [{'text': 'claim', 'citations': [{'chunk_id': 'e1', 'quote': 'q',
                                                            'source_id': 's1'}],
                           'evidence_status': 'supported',
                           'applicability': 'documented_alignment'}]}
        (jobs / 'Q001--ignis.json').write_text(
            json.dumps({'question_id': 'Q001', 'run': run}), encoding='utf-8')
        result = self.post_json('/api/axiom/trace-demo', {'preset': 'remove_validation'})
        self.assertEqual(result['mutation']['event_type'], 'METADATA_VALIDATED')
        self.assertEqual(result['reference']['overall'], 'PASS')
        self.assertNotIn('METADATA_VALIDATED', [event['type'] for event in result['mutated']['events']])
        self.assertFalse(result_path.parent.joinpath('trace-demo.json').exists())
        self.assert_http_error(400, lambda: self.post_json('/api/axiom/trace-demo',
                                                            {'preset': 'unknown'}))

    def test_demo_endpoints_replay_with_get_without_constructing_models(self):
        card = {'id':'synthetic-demo','title':'Synthetic saved example'}
        saved = {'demo':card,'run':{'answer':'Saved answer','claims':[]},'replay':True}
        with patch('axiom.demo.list_demos', return_value=[card]), \
             patch('axiom.demo.get_demo', return_value=saved) as get_demo, \
             patch('axiom.server.make_model', side_effect=AssertionError('No inference during replay')):
            with self.opener.open(self.url + '/api/demos') as response:
                self.assertEqual(json.load(response)['demos'], [card])
            with self.opener.open(self.url + '/api/demos/synthetic-demo') as response:
                self.assertTrue(json.load(response)['replay'])
            get_demo.assert_called_once_with(self.root, 'synthetic-demo')

    def test_demo_endpoints_preserve_host_and_missing_record_checks(self):
        with patch('axiom.demo.list_demos') as list_demos:
            req = urllib.request.Request(self.url + '/api/demos', headers={'Host':'evil.example'})
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.opener.open(req)
            self.assertEqual(raised.exception.code, 403)
            list_demos.assert_not_called()
        with patch('axiom.demo.get_demo', side_effect=FileNotFoundError):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.opener.open(self.url + '/api/demos/missing')
            self.assertEqual(raised.exception.code, 404)

    def test_filter_options_reach_research(self):
        req = urllib.request.Request(self.url + "/api/ask", json.dumps({"question":"airflow", "source_ids":["absent"]}).encode(), {"Content-Type":"application/json"})
        with self.opener.open(req) as response:
            result = json.load(response)
        self.assertEqual(result["evidence"], [])
        self.assertTrue(result["abstained"])

    def test_filter_type_error_is_reported(self):
        req = urllib.request.Request(self.url + "/api/ask", b'{"question":"airflow","experiments":"BASS"}', {"Content-Type":"application/json"})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.opener.open(req)
        self.assertEqual(raised.exception.code,400)

    def get_json(self, path, headers=None):
        request = urllib.request.Request(self.url + path, headers=headers or {})
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def post_json(self, path, value, headers=None):
        request = urllib.request.Request(self.url + path, json.dumps(value).encode(),
                                         {'Content-Type': 'application/json', **(headers or {})})
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def assert_http_error(self, status, callback):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            callback()
        try:
            self.assertEqual(raised.exception.code, status)
            self.assertTrue(json.load(raised.exception)['error'])
        finally:
            raised.exception.close()

    def fixture_run(self, identifier, question='Synthetic airflow question', date='2026-11-04T10:00:00Z'):
        return {'run_id': identifier, 'created_at': date, 'question': question,
                'answer': 'Synthetic saved evidence.', 'answer_status': 'source_excerpts',
                'claims': [{'text': 'Preserve this fixture.', 'citations': []}],
                'model_info': {'provider': 'ollama', 'model': 'fixture-model'}}

    def fixture_comparison(self, identifier='comparison-1'):
        return {'comparison_id': identifier, 'created_at': '2026-11-04T10:00:00Z',
                'question': 'Synthetic airflow question', 'baseline': self.fixture_run('baseline-1'),
                'ignis': self.fixture_run('ignis-1'), 'controls': {'provider': 'ollama', 'model': 'fixture-model'},
                'status': 'complete', 'errors': {}, 'saved_locally': True}

    def test_saved_run_reopens_full_record_with_list_search_and_pagination(self):
        records = [self.fixture_run('older', date='2026-11-03T10:00:00Z'),
                   self.fixture_run('newer', date='2026-11-04T10:00:00Z'),
                   self.fixture_run('unrelated', question='Synthetic geometry question', date='2026-11-05T10:00:00Z')]
        for record in records:
            save_run(self.root, record)
        result = self.get_json('/api/runs?q=AIRFLOW&limit=1&offset=1')
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['skipped'], 0)
        self.assertEqual([row['run_id'] for row in result['runs']], ['older'])
        self.assertEqual(result['runs'][0]['model_info']['model'], 'fixture-model')
        self.assertNotIn('claims', result['runs'][0])
        self.assertEqual(self.get_json('/api/runs/newer'), records[1])
        self.assertEqual(self.get_json('/api/runs?offset=99')['runs'], [])

    def test_asked_answer_is_available_in_saved_history(self):
        result = self.post_json('/api/ask', {'question': 'BASS-II airflow'})
        self.assertTrue(result['saved_locally'])
        reopened = self.get_json('/api/runs/' + result['run_id'])
        self.assertEqual(reopened['answer'], result['answer'])
        self.assertEqual(reopened['draft_checks'], result['draft_checks'])
        self.assertEqual(self.get_json('/api/runs')['runs'][0]['run_id'], result['run_id'])

    def test_answer_storage_failure_preserves_exportable_response(self):
        for failure in (OSError('Fixture disk failure'), ValueError('Fixture record bounds')):
            with self.subTest(failure=type(failure).__name__), patch('axiom.run_records.save_run', side_effect=failure):
                result = self.post_json('/api/ask', {'question': 'BASS-II airflow'})
                self.assertTrue(result['answer'])
                self.assertFalse(result['saved_locally'])
                self.assertIn('could not be saved', result['save_error'])

    def test_saved_comparison_reopens_both_results_and_searches(self):
        record = self.fixture_comparison()
        save_comparison(self.root, record)
        save_comparison(self.root, dict(record, comparison_id='comparison-2', question='Geometry fixture'))
        self.assertEqual(self.get_json('/api/comparisons/comparison-1'), record)
        result = self.get_json('/api/comparisons?q=airflow&limit=1&offset=0')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['skipped'], 0)
        self.assertEqual(result['comparisons'][0]['comparison_id'], 'comparison-1')
        self.assertEqual(result['comparisons'][0]['status'], 'complete')
        self.assertEqual(self.get_json('/api/comparisons?limit=1&offset=1')['comparisons'][0]['comparison_id'], 'comparison-2')

    def test_saved_endpoints_reject_invalid_ids_queries_and_missing_files(self):
        for collection in ('runs', 'comparisons'):
            with self.subTest(collection=collection):
                self.assert_http_error(404, lambda: self.get_json('/api/' + collection + '/missing'))
                for suffix in ('/../secret', '/%2e%2e%2fsecret', '/nested/id', '/'):
                    self.assert_http_error(400, lambda: self.get_json('/api/' + collection + suffix))
                for query in ('limit=0', 'limit=101', 'offset=-1', 'limit=abc', 'limit=1&limit=2', 'unknown=x', 'q=' + 'x' * 501):
                    self.assert_http_error(400, lambda: self.get_json('/api/' + collection + '?' + query))

    def test_malformed_saved_records_are_skipped_and_direct_load_is_rejected(self):
        path = save_run(self.root, self.fixture_run('valid'))
        (path.parent / 'broken.json').write_text('{', encoding='utf-8')
        self.assertEqual(self.get_json('/api/runs')['skipped'], 1)
        self.assert_http_error(400, lambda: self.get_json('/api/runs/broken'))

    def test_history_and_comparison_reject_invalid_host_before_work(self):
        with patch('axiom.comparison.compare') as compare, patch('axiom.server.make_model') as model:
            for endpoint in ('/api/runs', '/api/runs/missing', '/api/comparisons', '/api/comparisons/missing'):
                self.assert_http_error(403, lambda: self.get_json(endpoint, {'Host': 'evil.example'}))
            self.assert_http_error(403, lambda: self.post_json('/api/compare', {'question': 'Fixture', 'provider': 'ollama'}, {'Host': 'evil.example'}))
            self.assert_http_error(403, lambda: self.post_json('/api/compare', {'question': 'Fixture', 'provider': 'ollama'}, {'Origin': 'https://evil.example'}))
            compare.assert_not_called()
            model.assert_not_called()

    def test_extractive_comparison_refused_before_model_initialization(self):
        with patch('axiom.comparison.make_model') as model:
            self.assert_http_error(400, lambda: self.post_json('/api/compare', {'question': 'Fixture question', 'provider': 'extractive'}))
            model.assert_not_called()

    def test_invalid_requests_rejected_before_comparison_or_model(self):
        invalid = [[], {}, {'question': ' '}, {'question': 'x' * 4001},
                   {'question': 'Fixture', 'provider': 'unsupported'},
                   {'question': 'Fixture', 'source_ids': 'source'},
                   {'question': 'Fixture', 'target': {'oxygen_percent': -1}},
                   {'question': 'Fixture', 'fresh': 'yes'},
                   {'question': 'Fixture', 'model': 123}]
        with patch('axiom.comparison.compare') as compare, patch('axiom.server.make_model') as model:
            for endpoint in ('/api/ask', '/api/compare'):
                for payload in invalid:
                    with self.subTest(endpoint=endpoint, payload=payload):
                        self.assert_http_error(400, lambda: self.post_json(endpoint, payload))
            compare.assert_not_called()
            model.assert_not_called()

    def test_mocked_comparison_preserves_partial_results_and_controls(self):
        pair = self.fixture_comparison()
        pair.update(status='partial', errors={'baseline': 'Synthetic provider failure.'})
        pair['baseline'].update(answer='', answer_status='execution_error', error='Synthetic provider failure.')
        payload = {'question': pair['question'], 'provider': 'ollama', 'model': 'fixture-model',
                   'experiments': ['BASS-II'], 'source_ids': ['source-fixture'], 'fresh': True,
                   'include_overviews': True, 'target': {'oxygen_percent': 21}, 'intent': 'research'}
        with patch('axiom.comparison.compare', return_value=pair) as compare, patch('axiom.server.make_model') as model:
            response = self.post_json('/api/compare', payload)
            self.assertEqual(response, pair)
            compare.assert_called_once()
            called_root, request = compare.call_args.args
            self.assertEqual(called_root, self.root)
            for key, value in payload.items():
                self.assertEqual(request[key], value)
            model.assert_not_called()

    def test_benchmark_read_endpoints_do_not_construct_models(self):
        latest = {'manifest':{'run_id':'pilot','status':'pending_source_scope','created_at':'2026-11-05T06:00:00Z',
                              'inputs':{'provider':'groq','model':'fixture','split':'dev'}},
                  'report':{'progress':{'overall':{'completed':2,'pending':34}}}}
        with patch('axiom.benchmark_audit.audit_benchmark',return_value={'question_count':36}) as audit, \
             patch('axiom.benchmark_run.latest_benchmark',return_value=latest), \
             patch('axiom.benchmark_run.benchmark_answers',return_value=[{'question_id':'Q001'}]) as answers, \
             patch('axiom.benchmark_run.make_model') as model:
            response=self.get_json('/api/benchmark')
            self.assertEqual(response['audit']['question_count'],36)
            self.assertEqual(response['latest']['run_id'],'pilot')
            self.assertEqual(self.get_json('/api/benchmark/pilot/answers')['answers'][0]['question_id'],'Q001')
            answers.assert_called_once_with(self.root,'pilot')
            model.assert_not_called()
            audit.assert_called_once()

    def test_benchmark_read_endpoints_reject_bad_hosts_and_ids(self):
        with patch('axiom.benchmark_audit.audit_benchmark') as audit:
            self.assert_http_error(403,lambda:self.get_json('/api/benchmark',{'Host':'evil.example'}))
            audit.assert_not_called()
        self.assert_http_error(400,lambda:self.get_json('/api/benchmark/../answers'))
        self.assert_http_error(404,lambda:self.get_json('/api/benchmark/missing/answers'))


    def test_impact_endpoint_reads_verified_metrics_without_models(self):
        summary={'schema_version':'benchmark-impact-v1','run_id':'synthetic','integrity_verified':True}
        with patch('axiom.benchmark_impact.summarize_impact',return_value=summary) as calculate, \
             patch('axiom.providers.make_model',side_effect=AssertionError('No inference')):
            self.assertEqual(self.get_json('/api/benchmark/synthetic/impact'),summary)
            calculate.assert_called_once_with(self.root,'synthetic',allow_integrity_warnings=True)

    def test_impact_route_serves_unverified_charts_independent_of_client_flags(self):
        # A hosted rewrite may drop query flags; the chart route must still
        # return the saved observations plus their explicit integrity warnings.
        unverified={'schema_version':'benchmark-impact-v1','run_id':'synthetic','integrity_verified':False,
                    'integrity_warnings':[{'code':'input_fingerprint_mismatch'}]}
        with patch('axiom.benchmark_impact.summarize_impact',return_value=unverified) as calculate:
            self.assertEqual(self.get_json('/api/benchmark/synthetic/impact'),unverified)
            self.assertEqual(self.get_json('/api/benchmark/synthetic/impact?observed_only=1'),unverified)
            for call in calculate.call_args_list:
                self.assertEqual(call.kwargs,{'allow_integrity_warnings':True})

    def test_impact_endpoint_preserves_host_path_and_integrity_boundaries(self):
        with patch('axiom.benchmark_impact.summarize_impact') as calculate:
            self.assert_http_error(403,lambda:self.get_json('/api/benchmark/synthetic/impact',{'Host':'evil.example'}))
            calculate.assert_not_called()
        self.assert_http_error(400,lambda:self.get_json('/api/benchmark/../impact'))
        self.assert_http_error(404,lambda:self.get_json('/api/benchmark/missing/impact'))
        with patch('axiom.benchmark_impact.summarize_impact',side_effect=ValueError('Synthetic integrity failure')):
            self.assert_http_error(400,lambda:self.get_json('/api/benchmark/synthetic/impact'))

    def test_scenario_endpoints_assess_save_list_and_plan_without_models(self):
        with patch('axiom.server.make_model', side_effect=AssertionError('No inference in scenario work')):
            meta = self.get_json('/api/scenario-metadata')
            self.assertEqual(len(meta['fields']), 10)
            self.assertEqual(meta['corpus']['documents'], 1)
            result = self.post_json('/api/scenario-assess',
                                    {'scenario': {'gravity': 'microgravity'}, 'save': True,
                                     'description': 'Synthetic gravity scenario'})
            self.assertTrue(result['saved_locally'])
            self.assertEqual(result['scenario_fields'], ['gravity'])
            identifier = result['scenario_id']
            self.assertEqual(self.get_json('/api/scenarios/' + identifier), result)
            listed = self.get_json('/api/scenarios')
            self.assertEqual(listed['total'], 1)
            self.assertEqual(listed['scenarios'][0]['scenario_id'], identifier)
            planned = self.post_json('/api/scenario-plan', {'scenario_id': identifier})
            self.assertTrue(planned['reused_assessment'])
            self.assertEqual(planned['target'], result['target'])
            self.assertIn('NOT EXECUTED', planned['label'])

    def test_scenario_endpoints_preserve_validation_host_origin_and_missing_record_checks(self):
        with patch('axiom.scenario.assess') as assess:
            self.assert_http_error(403, lambda: self.get_json('/api/scenario-metadata', {'Host': 'evil.example'}))
            self.assert_http_error(403, lambda: self.post_json('/api/scenario-assess', {'scenario': {}},
                                                               {'Host': 'evil.example'}))
            self.assert_http_error(403, lambda: self.post_json('/api/scenario-assess', {'scenario': {}},
                                                               {'Origin': 'https://evil.example'}))
            assess.assert_not_called()
        for query in ('limit=0', 'limit=101', 'offset=-1', 'limit=abc', 'unknown=x'):
            self.assert_http_error(400, lambda: self.get_json('/api/scenarios?' + query))
        self.assert_http_error(400, lambda: self.get_json('/api/scenarios/../secret'))
        self.assert_http_error(404, lambda: self.get_json('/api/scenarios/missing'))
        self.assert_http_error(400, lambda: self.post_json('/api/scenario-assess',
                                                           {'scenario': {'unknown': 'value'}}))
        self.assert_http_error(400, lambda: self.post_json('/api/scenario-assess', {'save': 'yes'}))
        self.assert_http_error(400, lambda: self.post_json('/api/scenario-plan', {'scenario_id': 'missing'}))
