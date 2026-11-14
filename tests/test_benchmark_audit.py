import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.benchmark_audit import audit_benchmark
from axiom.retrieval import search


class BenchmarkAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'benchmarks').mkdir()
        (self.root / 'data/processed').mkdir(parents=True)
        self.reference_url = 'https://ntrs.nasa.gov/citations/12345'
        self.inventory = [{'source_id': 'ntrs-12345', 'url': self.reference_url,
                           'download_url': 'https://ntrs.nasa.gov/api/citations/12345/downloads/12345.pdf',
                           'source_kind': 'research_presentation', 'permission_status': 'allowed', 'status': 'active'}]
        self.references = {'NAMED': {'url': self.reference_url, 'kind': 'technical report', 'locator': 'Full document'}}
        self.chunks = [self.chunk()]
        self.questions = [self.question()]
        self.write_inputs()
        self.scope_patch = patch('axiom.benchmark_audit.load_scope_chunks', return_value=[])
        self.scope_mock = self.scope_patch.start()
        self.addCleanup(self.scope_patch.stop)

    def chunk(self, identifier='named-page', **updates):
        text = 'Synthetic airflow observations were reported in this experiment.'
        result = {'chunk_id': identifier, 'source_id': 'ntrs-12345', 'text': text,
                  'sha256': hashlib.sha256(text.encode()).hexdigest(), 'title': 'Synthetic airflow report',
                  'url': self.reference_url, 'source_kind': 'research_presentation',
                  'experiment': 'BASS', 'locator': 'PDF page 1, text part 1', 'evidence_tier': 2,
                  'conditions': {'gravity': None, 'fuel': None, 'oxygen_percent': None, 'pressure_kpa': None, 'flow_cm_s': None}}
        result.update(updates)
        result['sha256'] = hashlib.sha256(result['text'].encode()).hexdigest()
        return result

    def question(self, **updates):
        result = {'question_id': 'Q001', 'question': 'What airflow observations were reported?',
                  'category': 'answerable', 'split': 'dev', 'reference_ids': ['NAMED'],
                  'reference_urls': [self.reference_url], 'annotation_status': 'ai_draft_unreviewed',
                  'human_reviewer': None, 'expected_action': 'answer', 'expected_abstained': False,
                  'rubric': 'SECRET EXPECTED ANSWER MUST NOT ENTER SEARCH', 'evidence_spans': []}
        result.update(updates)
        return result

    def write_inputs(self):
        (self.root / 'data/sources.json').write_text(json.dumps({'sources': self.inventory}), encoding='utf-8')
        (self.root / 'data/processed/chunks.jsonl').write_text('\n'.join(map(json.dumps, self.chunks)), encoding='utf-8')
        (self.root / 'benchmarks/sources.json').write_text(json.dumps(self.references), encoding='utf-8')
        (self.root / 'benchmarks/questions.jsonl').write_text('\n'.join(map(json.dumps, self.questions)), encoding='utf-8')

    def test_read_only_deterministic_candidates_preserve_exact_quote_locator_and_hash(self):
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        first = audit_benchmark(self.root)
        self.assertEqual(first, audit_benchmark(self.root))
        after = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        row = first['questions'][0]
        self.assertEqual(row['readiness'], 'candidates_need_review')
        self.assertEqual(row['allowed_chunk_ids'], ['named-page'])
        candidate = row['candidates'][0]
        self.assertEqual(candidate['quote'], self.chunks[0]['text'])
        self.assertEqual(candidate['locator'], self.chunks[0]['locator'])
        self.assertEqual(candidate['quote_sha256'], self.chunks[0]['sha256'])
        self.assertTrue(candidate['in_reference_scope'])
        self.assertFalse(row['auto_scoring_ready'])

    def test_query_uses_question_only_and_candidates_are_restricted_to_reference(self):
        unrelated = dict(self.inventory[0], source_id='another', url='https://ntrs.nasa.gov/citations/98765')
        self.inventory.append(unrelated)
        self.chunks.extend([self.chunk('outside', source_id='another', text='SECRET EXPECTED ANSWER airflow observations.'),
                            self.chunk('page2', text='Airflow observations included a second synthetic condition.'),
                            self.chunk('page3', text='Airflow observations included a third synthetic condition.'),
                            self.chunk('page4', text='Airflow observations included a fourth synthetic condition.')])
        self.write_inputs()
        original = copy.deepcopy(self.questions)
        with patch('axiom.benchmark_audit.search', wraps=search) as retrieve:
            row = audit_benchmark(self.root, self.questions)['questions'][0]
        self.assertEqual(retrieve.call_args.args[0], self.questions[0]['question'])
        self.assertEqual(retrieve.call_args.kwargs['source_ids'], ['ntrs-12345'])
        self.assertTrue(retrieve.call_args.kwargs['include_overviews'])
        self.assertLessEqual(len(row['candidates']), 3)
        self.assertTrue(all(candidate['source_id'] == 'ntrs-12345' for candidate in row['candidates']))
        self.assertEqual(self.questions, original)

    def test_abstract_reference_does_not_silently_use_pdf(self):
        self.references['NAMED'].update(locator='Abstract', kind='presentation abstract')
        self.write_inputs()
        row = audit_benchmark(self.root)['questions'][0]
        self.assertEqual(row['readiness'], 'reference_scope_missing')
        self.assertEqual(row['allowed_chunk_ids'], [])
        self.assertEqual(row['allowed_source_ids'], [])
        self.assertTrue(row['abstract_only'])
        self.assertFalse(row['references'][0]['scope_available'])
        self.assertTrue(row['candidates'])
        self.assertTrue(all(not candidate['in_reference_scope'] for candidate in row['candidates']))

    def test_explicit_metadata_abstract_is_allowed_but_full_pdf_is_excluded(self):
        self.references['NAMED'].update(locator='Abstract', kind='presentation abstract')
        self.write_inputs()
        abstract = self.chunk('named-abstract', locator='NTRS metadata abstract', source_kind='presentation_abstract')
        self.scope_mock.return_value = [abstract]
        row = audit_benchmark(self.root)['questions'][0]
        self.assertTrue(row['all_reference_scopes_available'])
        self.assertEqual(row['allowed_chunk_ids'], ['named-abstract'])
        self.assertEqual([candidate['chunk_id'] for candidate in row['candidates']], ['named-abstract'])

    def test_catalog_non_ingested_and_unknown_references_remain_missing(self):
        cases = [('catalog', {'kind': 'dataset catalog'}, 'catalog_not_measurement_corpus'),
                 ('missing', {'url': 'https://science.nasa.gov/absent/'}, 'reference_not_in_inventory')]
        for _, changes, status in cases:
            with self.subTest(status=status):
                self.references['NAMED'] = {'url': self.reference_url, 'locator': 'Full document', **changes}
                self.write_inputs()
                row = audit_benchmark(self.root)['questions'][0]
                self.assertEqual(row['references'][0]['scope_status'], status)
                self.assertEqual(row['allowed_chunk_ids'], [])
                self.assertEqual(row['candidates'], [])
        self.references['NAMED'] = {'url': self.reference_url, 'locator': 'Full document'}
        self.chunks = []
        self.write_inputs()
        self.assertEqual(audit_benchmark(self.root)['questions'][0]['references'][0]['scope_status'], 'source_not_ingested')
        row = audit_benchmark(self.root, [self.question(reference_ids=['UNKNOWN'])])['questions'][0]
        self.assertEqual(row['allowed_chunk_ids'], [])
        self.assertTrue(row['warnings'])

    def test_permission_hold_is_not_generation_evidence(self):
        self.inventory[0]['permission_status'] = 'hold'
        self.write_inputs()
        row = audit_benchmark(self.root)['questions'][0]
        self.assertEqual(row['references'][0]['scope_status'], 'source_not_eligible')
        self.assertEqual(row['allowed_chunk_ids'], [])

    def test_catalog_sections_require_verified_descriptions_from_named_loader(self):
        self.references['NAMED'].update(kind='dataset catalog', locator='Objectives; Files; DOI')
        self.inventory[0].update(source_kind='dataset_catalog', status='catalog_only_not_downloaded')
        def section(chunk_id, section_name, **updates):
            return self.chunk(chunk_id, source_kind='dataset_catalog', section=section_name,
                              named_scope_verified=True, evidence_role='source_description',
                              permission_status='allowed', status='active', **updates)
        # A marker copied into the main corpus cannot authenticate a catalog snapshot.
        self.chunks = [section('untrusted-main', 'Objectives')]
        self.write_inputs()
        verified = [section(name.lower(), name) for name in ('Objectives', 'Files', 'DOI', 'License', 'Archived Files')]
        named_inventory = [dict(self.inventory[0], status='active')]
        with patch('axiom.benchmark_audit.load_named_chunks', return_value=verified), \
             patch('axiom.benchmark_audit.load_named_inventory', return_value=named_inventory):
            row = audit_benchmark(self.root)['questions'][0]
            self.assertTrue(row['all_reference_scopes_available'])
            self.assertEqual(row['allowed_chunk_ids'], ['doi', 'files', 'objectives'])
            self.assertEqual(row['references'][0]['inventory_statuses'], {'ntrs-12345': 'active'})
            self.assertTrue(any('Numerical measurements require' in w for w in row['warnings']))
            self.assertFalse(row['auto_scoring_ready'])
            only = self.question(question='Using only the PSI-98 catalog objectives, what was its stated aim?')
            restricted = audit_benchmark(self.root, [only])['questions'][0]
            self.assertEqual(restricted['allowed_chunk_ids'], ['objectives'])
            self.assertEqual(restricted['references'][0]['effective_locator'], 'objectives')
            verified[:] = [c for c in verified if c['section'] != 'Files']
            partial = audit_benchmark(self.root)['questions'][0]
            self.assertFalse(partial['all_reference_scopes_available'])
            self.assertEqual(partial['references'][0]['missing_scope_locators'], ['files'])
            self.assertEqual(partial['allowed_chunk_ids'], [])

    def test_normal_paper_or_unverified_chunk_cannot_satisfy_catalog(self):
        self.references['NAMED'].update(kind='dataset catalog', locator='Objectives')
        self.write_inputs()
        for change in ({'evidence_role': 'experiment_result'}, {'named_scope_verified': False}):
            candidate = dict(self.chunk('fake', section='Objectives'), evidence_role='source_description',
                             named_scope_verified=True, permission_status='allowed', status='active')
            candidate.update(change)
            with self.subTest(change=change), patch('axiom.benchmark_audit.load_named_chunks', return_value=[candidate]):
                row = audit_benchmark(self.root)['questions'][0]
                self.assertFalse(row['all_reference_scopes_available'])
                self.assertEqual(row['allowed_chunk_ids'], [])

    def test_abstract_alone_does_not_satisfy_reference_requiring_report_section(self):
        self.references['NAMED'].update(locator='Abstract; report section 4.2')
        self.write_inputs()
        self.scope_mock.return_value = [self.chunk('abstract', locator='NTRS metadata abstract')]
        row = audit_benchmark(self.root)['questions'][0]
        self.assertFalse(row['all_reference_scopes_available'])
        self.assertEqual(row['allowed_chunk_ids'], [])
        self.assertEqual(row['references'][0]['missing_scope_locators'], ['report section 4.2'])

    def test_url_mismatch_blocks_generation_even_when_id_maps(self):
        row = audit_benchmark(self.root, [self.question(reference_urls=['https://ntrs.nasa.gov/citations/OTHER'])])['questions'][0]
        self.assertEqual(row['readiness'], 'reference_mapping_incomplete')
        self.assertEqual(row['allowed_chunk_ids'], [])
        self.assertFalse(row['all_reference_scopes_available'])

    def test_names_and_ai_annotations_are_not_qualified_reviews_or_scores(self):
        questions = [self.question(human_reviewer='Named person', category='extrapolation'),
                     self.question(question_id='Q002', annotation_status='review_recorded',
                                   qualified_review={'status': 'completed', 'reviewer': 'Fixture person',
                                                     'qualification': 'Documented fixture qualification', 'reviewed_at': '2026-11-05'},
                                   expected_abstained=True)]
        result = audit_benchmark(self.root, questions)
        self.assertEqual(result['counts']['ai_draft_unreviewed'], 1)
        self.assertEqual(result['counts']['human_reviewer_recorded'], 1)
        self.assertEqual(result['counts']['qualified_review_documented'], 1)
        self.assertEqual(result['counts']['abstention_or_trap'], 2)
        self.assertEqual(result['counts']['auto_scoring_ready'], 0)
        self.assertTrue(all(row['requires_scientific_review'] for row in result['questions']))
        self.assertTrue(all(not row['review']['qualification_independently_verified'] for row in result['questions']))

    def test_overview_can_be_explicit_reference_without_certifying_findings(self):
        self.chunks = [self.chunk(source_kind='experiment_overview')]
        self.write_inputs()
        row = audit_benchmark(self.root)['questions'][0]
        self.assertTrue(row['candidates'])
        self.assertFalse(row['auto_scoring_ready'])

    def test_integrity_failure_and_duplicate_questions_fail_closed(self):
        with self.assertRaises(ValueError):
            audit_benchmark(self.root, self.questions * 2)
        self.chunks[0]['sha256'] = 'not-the-text-hash'
        self.write_inputs()
        with self.assertRaises(ValueError):
            audit_benchmark(self.root)


if __name__ == '__main__':
    unittest.main()
