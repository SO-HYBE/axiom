"""Named catalog descriptions may support claims about the source's contents."""
from copy import deepcopy
import hashlib
import unittest
from unittest.mock import patch

from axiom.critic import CONDITIONS
from axiom.model import DRAFT_SCHEMA, REVIEW_SCHEMA, LocalModel
from axiom.research import run
from axiom.retrieval import search
from axiom.providers import HostedModel


def catalog(**changes):
    text = 'The synthetic catalog lists droplet observations as an investigation objective.'
    result = {'chunk_id': 'catalog-objectives', 'source_id': 'catalog', 'title': 'Synthetic catalog',
              'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest(), 'experiment': 'FLEX',
              'locator': 'Objectives, paragraph 1', 'url': 'https://example.invalid/catalog',
              'source_kind': 'dataset_catalog', 'permission_status': 'allowed', 'status': 'active',
              'evidence_role': 'source_description', 'named_scope_verified': True, 'evidence_tier': 4,
              'conditions': {field: None for field in CONDITIONS}}
    result.update(changes)
    return result


class RecordingModel(LocalModel):
    def __init__(self):
        super().__init__('fixture')
        self.prompts = []

    def complete(self, instruction, payload, schema):
        self.prompts.append((instruction, deepcopy(payload)))
        chunk = payload['evidence'][0]
        citation = {'source_id': chunk['source_id'], 'chunk_id': chunk['chunk_id'], 'quote': chunk['text']}
        if schema == DRAFT_SCHEMA:
            return {'abstained': False, 'reason': 'Synthetic source description.', 'claims': [{
                'text': chunk['text'], 'claim_type': 'source_description', 'citations': [citation]}]}
        if schema == REVIEW_SCHEMA:
            return {'verdict': 'supported', 'reason': 'Synthetic description.', 'uncertainty': 'Scope limited.',
                    'evidence_checks': [dict(citation, relation='supports')]}
        raise AssertionError('Unexpected generation request')


class SourceDescriptionRetrievalTests(unittest.TestCase):
    def test_hosted_group_review_receives_source_role_guidance(self):
        source = catalog()
        response = {'reviews': [{'claim_id': 'claim-0', 'verdict': 'supported',
            'reason': 'Synthetic source description.', 'uncertainty': 'No measurements supplied.',
            'evidence_checks': [dict(source_id=source['source_id'], chunk_id=source['chunk_id'],
                                     quote=source['text'], relation='supports')]}]}
        model = HostedModel('groq', 'fixture', 'test-placeholder')
        with patch.object(model, 'complete', return_value=response) as complete:
            model.review_many([source['text']], [source])
        self.assertIn('measured outcomes', complete.call_args.args[0])
        self.assertIn('source_description', complete.call_args.args[0])

    def test_only_explicit_opt_in_allows_named_catalog_descriptions(self):
        for kind in ('dataset_catalog', 'catalog'):
            source = catalog(source_kind=kind)
            with self.subTest(kind=kind):
                for options in ({}, {'include_overviews': True}, {'include_source_descriptions': 'true'}):
                    self.assertEqual(search('droplet', [source], **options), [])
                hits = search('droplet', [source], include_source_descriptions=True)
                self.assertEqual([hit['chunk_id'] for hit in hits], ['catalog-objectives'])

    def test_flag_does_not_bypass_scope_permission_status_or_existing_filters(self):
        for changes in ({'named_scope_verified': False}, {'named_scope_verified': 1},
                        {'evidence_role': 'measurement'}, {'permission_status': 'review_required'},
                        {'status': 'quarantined'}, {'source_kind': 'metadata'}, {'source_kind': 'overview_metadata'}):
            with self.subTest(changes=changes):
                self.assertEqual(search('droplet', [catalog(**changes)], include_source_descriptions=True), [])
        for field in ('permission_status', 'evidence_role', 'named_scope_verified'):
            source = catalog()
            del source[field]
            self.assertEqual(search('droplet', [source], include_source_descriptions=True), [])
        for options in ({'source_ids': ['other']}, {'experiments': ['BASS']}):
            self.assertEqual(search('droplet', [catalog()], include_source_descriptions=True, **options), [])

    def test_opted_in_runs_record_role_and_grounding_instruction_for_both_models(self):
        source = catalog()
        original = deepcopy(source)
        model = RecordingModel()
        result = run('What droplet observations are listed?', [source], model=model, include_source_descriptions=True)
        self.assertEqual(len(model.prompts), 2)
        for instruction, payload in model.prompts:
            self.assertIn('measured outcomes', instruction)
            self.assertIn('source_description', instruction)
            self.assertEqual(payload['evidence'][0]['evidence_role'], 'source_description')
            self.assertEqual(payload['evidence'][0]['conditions'], original['conditions'])
        self.assertTrue(result['retrieval_config']['include_source_descriptions'])
        self.assertEqual(result['claims'][0]['claim_type'], 'source_description')
        self.assertEqual(source, original)

    def test_unknown_conditions_stay_unknown_for_transfer_questions(self):
        source = catalog()
        result = run('Droplet observations?', [source], model=RecordingModel(), target={'pressure_kpa': 100},
                     include_source_descriptions=True)
        self.assertTrue(result['abstained'])
        self.assertIn('condition_unknown:pressure_kpa', result['draft_checks'][0]['issues'])
        self.assertEqual(result['evidence'][0]['ranking']['applicability']['status'], 'unknown')

    def test_default_research_excludes_catalog_and_preserves_unmarked_prompt_shape(self):
        model = RecordingModel()
        result = run('Droplet observations?', [catalog()], model=model)
        self.assertTrue(result['abstained'])
        self.assertFalse(result['retrieval_config']['include_source_descriptions'])
        self.assertEqual(model.prompts, [])
        source = catalog(source_kind='technical_report')
        del source['evidence_role']
        run('Droplet observations?', [source], model=model)
        self.assertEqual(len(model.prompts), 2)
        for instruction, payload in model.prompts:
            self.assertNotIn('evidence_role', payload['evidence'][0])
            self.assertNotIn('A catalog passage marked', instruction)


if __name__ == '__main__':
    unittest.main()
