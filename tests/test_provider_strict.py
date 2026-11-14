"""Strict review format applies only to the documented model and review schemas."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.model import BATCH_REVIEW_SCHEMA, DRAFT_SCHEMA, REVIEW_SCHEMA
from axiom.provider_limits import Limiter
from axiom.providers import CACHE_VERSION, HostedModel, _digest


MODEL = 'qwen/qwen3.8-27b'
KEY = 'synthetic-strict-review-key'
RESULT = {'claims': [], 'abstained': True, 'reason': 'Synthetic abstention.'}


def reply(result):
    return {'http_status': 200, 'body': json.dumps({'model': MODEL, 'choices': [
        {'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}],
        'usage': {'prompt_tokens': 6, 'completion_tokens': 3, 'total_tokens': 9}})}


def closed_required_objects(schema):
    if schema.get('type') == 'object':
        if schema.get('additionalProperties') is not False:
            return False
        if set(schema.get('properties', {})) != set(schema.get('required', [])):
            return False
        return all(closed_required_objects(child) for child in schema.get('properties', {}).values())
    if schema.get('type') == 'array':
        return closed_required_objects(schema['items'])
    return True


class StrictReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=os.environ.get('AXIOM_TEST_TMPDIR'))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.evidence = [{'source_id': 'synthetic-source', 'chunk_id': 'synthetic-chunk',
                          'text': 'The synthetic observation reports 0.5 mW in the stated conditions.'}]
        self.review = {'verdict': 'supported', 'reason': 'Synthetic support.',
                       'uncertainty': 'Synthetic context only.', 'evidence_checks': [{
                           'source_id': 'synthetic-source', 'chunk_id': 'synthetic-chunk',
                           'quote': self.evidence[0]['text'], 'relation': 'supports'}]}

    def model(self, name=MODEL, provider='groq', cache=False):
        return HostedModel(provider, name, KEY, timeout=3,
                           cache_dir=self.root / 'cache' if cache else None, limiter=Limiter(0))

    def test_documented_model_receives_strict_copy_with_existing_quote_minimum(self):
        model = self.model()
        for schema in (REVIEW_SCHEMA, BATCH_REVIEW_SCHEMA):
            with self.subTest(schema=list(schema['properties'])):
                original = deepcopy(schema)
                body = model._body('Synthetic instruction.', {}, schema)
                formatting = body['response_format']
                self.assertEqual(formatting['type'], 'json_schema')
                self.assertEqual(formatting['json_schema']['name'], 'ignis_review')
                self.assertIs(formatting['json_schema']['strict'], True)
                expected = deepcopy(original)
                properties = expected['properties']
                if schema == BATCH_REVIEW_SCHEMA:
                    properties = properties['reviews']['items']['properties']
                properties['evidence_checks']['items']['properties']['quote']['minLength'] = 15
                self.assertEqual(formatting['json_schema']['schema'], expected)
                self.assertTrue(closed_required_objects(formatting['json_schema']['schema']))
                self.assertEqual(schema, original)
                self.assertFalse(body['stream'])
                self.assertEqual(body['temperature'], 0)
                self.assertEqual(body['max_tokens'], 1500)

    def test_request_owns_a_schema_copy_and_cannot_mutate_local_validator_contract(self):
        original = deepcopy(REVIEW_SCHEMA)
        body = self.model()._body('Synthetic request.', {}, REVIEW_SCHEMA)
        body['response_format']['json_schema']['schema']['properties']['verdict']['enum'].append('unverified-new-value')
        self.assertEqual(REVIEW_SCHEMA, original)

    def test_strict_prompt_requests_an_instance_and_exact_keys_without_inline_schema(self):
        for schema in (REVIEW_SCHEMA, BATCH_REVIEW_SCHEMA):
            body = self.model()._body('Synthetic review request.', {}, schema)
            instruction = body['messages'][0]['content']
            self.assertIn('JSON INSTANCE', instruction)
            self.assertIn(json.dumps(list(schema['properties'])), instruction)
            self.assertIn('verdict, never ver', instruction)
            self.assertIn('Never rename fields', instruction)
            self.assertIn('schema declarations such as type, properties, or required', instruction)
            self.assertNotIn('Return only JSON matching this schema:', instruction)
            self.assertNotIn('"type": "object"', instruction)

    def test_draft_protocol_and_existing_cache_identity_are_preserved(self):
        model = self.model(cache=True)
        instruction, payload = 'Synthetic draft request.', {'question': 'A synthetic question?', 'evidence': []}
        legacy_body = {'model': MODEL, 'stream': False, 'temperature': 0, 'max_tokens': 1500,
            'response_format': {'type': 'json_object'},
            'messages': [{'role': 'system', 'content': instruction + '\nReturn only JSON matching this schema: ' + json.dumps(DRAFT_SCHEMA)},
                         {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
        self.assertEqual(model._body(instruction, payload, DRAFT_SCHEMA), legacy_body)
        request_hash = _digest({'version': CACHE_VERSION, 'provider': 'groq', 'body': legacy_body, 'schema': DRAFT_SCHEMA})
        entry = {'version': CACHE_VERSION, 'request_hash': request_hash,
                 'result': RESULT, 'result_sha256': _digest(RESULT),
                 'usage': {'prompt_tokens': 6, 'completion_tokens': 3, 'total_tokens': 9}}
        model.cache_dir.mkdir()
        (model.cache_dir / (request_hash + '.json')).write_text(json.dumps(entry), encoding='utf-8')
        with patch('axiom.providers._transport', side_effect=AssertionError('Existing draft cache must replay')):
            self.assertEqual(model.complete(instruction, payload, DRAFT_SCHEMA), RESULT)
        self.assertEqual(model.calls[-1]['status'], 'cache_hit')

    def test_unknown_and_custom_groq_models_keep_json_object_mode(self):
        for name in ('synthetic-model', MODEL + '-custom', 'openai/gpt-oss-20b'):
            with self.subTest(name=name):
                body = self.model(name=name)._body('Synthetic request.', {}, BATCH_REVIEW_SCHEMA)
                self.assertEqual(body['response_format'], {'type': 'json_object'})
                self.assertIn('Return only JSON matching this schema:', body['messages'][0]['content'])
        self.assertEqual(self.model()._body('Synthetic generic request.', {}, {})['response_format'], {'type': 'json_object'})

    def test_openrouter_formats_and_free_only_routing_are_unchanged(self):
        for name, expected in [('synthetic:free', {'type': 'json_object'}),
                               ('nemotron-super-vl', {'type': 'json_object'}), ('nemotron-ultra', None)]:
            with self.subTest(name=name):
                body = self.model(name=name, provider='openrouter')._body('Synthetic request.', {}, BATCH_REVIEW_SCHEMA)
                self.assertEqual(body.get('response_format'), expected)
                self.assertEqual(body['provider']['max_price'], {'prompt': 0, 'completion': 0})
                self.assertIs(body['provider']['allow_fallbacks'], False)

    def test_valid_single_and_batch_reviews_keep_context_validation(self):
        model = self.model()
        with patch('axiom.providers._transport', return_value=reply(self.review)) as send:
            checked = model.review('Synthetic observation.', self.evidence)
        self.assertEqual(checked['verdict'], 'supported')
        self.assertEqual(send.call_args.args[2]['response_format']['type'], 'json_schema')
        batch = {'reviews': [dict(self.review, claim_id='claim-0')]}
        with patch('axiom.providers._transport', return_value=reply(batch)) as send:
            checked = model.review_many(['Synthetic observation.'], self.evidence)
        self.assertEqual(checked[0]['verdict'], 'supported')
        self.assertEqual(send.call_args.args[2]['response_format']['type'], 'json_schema')

    def test_http_200_extra_fields_and_renamed_verdict_still_fail_and_never_cache(self):
        bad_extra = dict(self.review, type='object')
        bad_rename = {('ver' if key == 'verdict' else key): value for key, value in self.review.items()}
        for result in (bad_extra, bad_rename):
            with self.subTest(shape=list(result)):
                model = self.model(cache=True)
                with patch('axiom.providers._transport', return_value=reply(result)) as send:
                    with self.assertRaises(ValueError):
                        model.review('Synthetic observation.', self.evidence)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(model.calls[-1]['status'], 'invalid_response')
                self.assertIn(model.calls[-1]['validation_error'],
                              ('model_response_schema_extra_fields', 'model_response_schema_missing_fields'))
                self.assertEqual(list(model.cache_dir.glob('*.json')), [])

    def test_schema_compliant_wrong_quote_remains_rejected(self):
        bad = deepcopy(self.review)
        bad['evidence_checks'][0]['quote'] = bad['evidence_checks'][0]['quote'].replace('mW', 'MW')
        model = self.model(cache=True)
        with patch('axiom.providers._transport', return_value=reply(bad)) as send:
            with self.assertRaises(ValueError):
                model.review('Synthetic observation.', self.evidence)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(model.calls[-1]['validation_error'], 'review_quote_mismatch')
        self.assertEqual(list(model.cache_dir.glob('*.json')), [])

    def test_short_quote_still_fails_locally_even_after_http_200(self):
        malformed = deepcopy(self.review)
        malformed['evidence_checks'][0]['quote'] = '0.5 mW'
        model = self.model(cache=True)
        with patch('axiom.providers._transport', return_value=reply(malformed)) as send:
            with self.assertRaises(ValueError):
                model.review('Synthetic observation.', self.evidence)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(model.calls[-1]['validation_error'], 'review_quote_too_short')
        self.assertEqual(list(model.cache_dir.glob('*.json')), [])
        effective = send.call_args.args[2]['response_format']['json_schema']['schema']
        self.assertEqual(effective['properties']['evidence_checks']['items']['properties']['quote']['minLength'], 15)
        self.assertNotIn('minLength', REVIEW_SCHEMA['properties']['evidence_checks']['items']['properties']['quote'])

    def test_provider_rejection_does_not_silently_downgrade_or_switch_model(self):
        model = self.model()
        with patch('axiom.providers._transport', return_value={'http_status': 400}) as send:
            with self.assertRaisesRegex(ValueError, 'HTTP 400'):
                model.review('Synthetic observation.', self.evidence)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[2]['model'], MODEL)
        self.assertEqual(send.call_args.args[2]['response_format']['type'], 'json_schema')
        self.assertEqual(model.calls[-1]['status'], 'http_error')

    def test_batch_schema_requires_exactly_one_two_or_three_supplied_ids(self):
        original = deepcopy(BATCH_REVIEW_SCHEMA)
        for count in (1, 2, 3):
            with self.subTest(count=count):
                claims = [{'claim_id':'claim-' + str(i), 'text':'Synthetic claim ' + str(i)} for i in range(count)]
                body = self.model()._body('Synthetic review request.', {'claims':claims, 'evidence':self.evidence}, BATCH_REVIEW_SCHEMA)
                reviews = body['response_format']['json_schema']['schema']['properties']['reviews']
                ids = [claim['claim_id'] for claim in claims]
                self.assertEqual((reviews['minItems'], reviews['maxItems']), (count, count))
                self.assertEqual(reviews['items']['properties']['claim_id']['enum'], ids)
                self.assertIn('Return exactly ' + str(count) + ' reviews', body['messages'][0]['content'])
                self.assertIn(json.dumps(ids), body['messages'][0]['content'])
                self.assertIn('Each ID must appear exactly once', body['messages'][0]['content'])
                self.assertEqual(BATCH_REVIEW_SCHEMA, original)

    def test_batch_cardinality_cannot_mutate_the_generic_schema(self):
        original = deepcopy(BATCH_REVIEW_SCHEMA)
        payload = {'claims':[{'claim_id':'claim-0','text':'Synthetic claim.'}]}
        body = self.model()._body('Synthetic review request.', payload, BATCH_REVIEW_SCHEMA)
        body['response_format']['json_schema']['schema']['properties']['reviews']['items']['properties']['claim_id']['enum'].append('invented')
        self.assertEqual(BATCH_REVIEW_SCHEMA, original)
        self.assertNotIn('minItems', BATCH_REVIEW_SCHEMA['properties']['reviews'])
        self.assertEqual(BATCH_REVIEW_SCHEMA['properties']['reviews']['maxItems'], 3)

    def test_omitted_review_still_fails_once_and_is_uncached(self):
        model = self.model(cache=True)
        omitted = {'reviews':[dict(self.review, claim_id='claim-0')]}
        with patch('axiom.providers._transport', return_value=reply(omitted)) as send:
            with self.assertRaises(ValueError):
                model.review_many(['Synthetic first claim.', 'Synthetic second claim.'], self.evidence)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(model.calls[-1]['validation_error'], 'review_claim_count_mismatch')
        self.assertEqual(list(model.cache_dir.glob('*.json')), [])
        reviews = send.call_args.args[2]['response_format']['json_schema']['schema']['properties']['reviews']
        self.assertEqual((reviews['minItems'], reviews['maxItems']), (2, 2))

    def test_duplicate_or_unrequested_output_ids_remain_rejected(self):
        for ids in [('claim-0', 'claim-0'), ('claim-0', 'unrequested')]:
            with self.subTest(ids=ids):
                model = self.model(cache=True)
                malformed = {'reviews':[dict(self.review, claim_id=identifier) for identifier in ids]}
                with patch('axiom.providers._transport', return_value=reply(malformed)) as send:
                    with self.assertRaises(ValueError):
                        model.review_many(['Synthetic first claim.', 'Synthetic second claim.'], self.evidence)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(model.calls[-1]['validation_error'], 'review_claim_id_mismatch')
                self.assertEqual(list(model.cache_dir.glob('*.json')), [])

    def test_invalid_or_absent_request_claims_do_not_create_partial_enum_constraints(self):
        for claims in (None, [], [{'claim_id':'','text':'Synthetic'}],
                       [{'claim_id':'claim-0','text':'Synthetic'}, {'claim_id':'claim-0','text':'Synthetic'}]):
            with self.subTest(claims=claims):
                body = self.model()._body('Synthetic request.', {'claims':claims}, BATCH_REVIEW_SCHEMA)
                effective = body['response_format']['json_schema']['schema']
                expected = deepcopy(BATCH_REVIEW_SCHEMA)
                expected['properties']['reviews']['items']['properties']['evidence_checks']['items']['properties']['quote']['minLength'] = 15
                self.assertEqual(effective, expected)

    def test_frozen_policy_names_only_review_schemas(self):
        self.assertEqual(self.model().retry_policy['review_format_policy'],
                         {'mode': 'strict_json_schema', 'schemas': ['semantic_review', 'batch_review'], 'version':3, 'batch_cardinality':'exact_requested_count', 'batch_claim_ids':'requested_id_enum_and_local_uniqueness', 'quote_min_characters':15})
        self.assertEqual(self.model(name='synthetic-model').retry_policy['review_format_policy'],
                         {'mode': 'provider_default', 'schemas': []})


if __name__ == '__main__':
    unittest.main()
