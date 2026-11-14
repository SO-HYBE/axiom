"""Rejected model messages stay rejected; optional evidence is bounded and safe."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.model import BATCH_REVIEW_SCHEMA, DRAFT_SCHEMA
from axiom.provider_limits import Limiter
from axiom.providers import (HostedModel, MAX_DIAGNOSTIC_CONTENT_BYTES, MAX_DIAGNOSTIC_FILE_BYTES,
                             _digest, make_model)


SECRET = 'fixture-diagnostic-key-do-not-persist'
RESULT = {'claims': [], 'abstained': True, 'reason': 'Synthetic abstention.'}


def reply(content, **extra):
    return {'http_status': 200, 'body': json.dumps(dict(model='synthetic-model', choices=[
        {'finish_reason': 'stop', 'message': {'content': content}}],
        usage={'prompt_tokens': 8, 'completion_tokens': 4, 'total_tokens': 12}, **extra))}


class ProviderDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=os.environ.get('AXIOM_TEST_TMPDIR'))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.diag = self.root / 'diagnostics'
        self.cache = self.root / 'cache'
        self.evidence = [{'chunk_id': 'synthetic-chunk', 'source_id': 'synthetic-source',
                          'text': 'The synthetic source reports 0.5 mW under the stated conditions.'}]

    def model(self, capture=True):
        return HostedModel('groq', 'synthetic-model', SECRET, timeout=3, cache_dir=self.cache,
                           limiter=Limiter(0), diagnostics_dir=self.diag if capture else None)

    def review(self, quote=None):
        return {'reviews': [{'claim_id': 'claim-0', 'verdict': 'supported',
            'reason': 'Synthetic support.', 'uncertainty': 'Synthetic conditions only.',
            'evidence_checks': [{'source_id': 'synthetic-source', 'chunk_id': 'synthetic-chunk',
                                 'quote': quote or self.evidence[0]['text'], 'relation': 'supports'}]}]}

    def read_diagnostic(self):
        files = list(self.diag.glob('*.json'))
        self.assertEqual(len(files), 1)
        self.assertLessEqual(files[0].stat().st_size, MAX_DIAGNOSTIC_FILE_BYTES)
        return files[0], json.loads(files[0].read_bytes())

    def test_quote_failure_retains_only_untrusted_model_text_and_safe_hashes(self):
        content = json.dumps(self.review('The synthetic source reports 0.5 MW under the stated conditions.'))
        model = self.model()
        with patch('axiom.providers._transport', return_value=reply(content, private_http_detail='DO_NOT_SAVE_ENVELOPE')) as send:
            with self.assertRaisesRegex(ValueError, 'invalid_response'):
                model.review_many(['A synthetic 0.5 mW observation.'], self.evidence)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(model.calls[0]['validation_error'], 'review_quote_mismatch')
        self.assertEqual(model.calls[0]['status'], 'invalid_response')
        self.assertEqual(model.calls[0]['usage']['total_tokens'], 12)
        self.assertEqual(list(self.cache.glob('*.json')), [])
        path, record = self.read_diagnostic()
        self.assertEqual(record['untrusted_model_content'], content)
        self.assertTrue(record['untrusted'])
        self.assertFalse(record['accepted'])
        self.assertEqual(record['validation_stage'], 'model_validation')
        self.assertEqual(record['validation_error'], 'review_quote_mismatch')
        self.assertEqual(record['model_content_sha256'], hashlib.sha256(content.encode()).hexdigest())
        self.assertEqual(path.name, model.calls[0]['diagnostic_file'])
        digest = record.pop('record_sha256')
        self.assertEqual(digest, _digest(record))
        self.assertNotIn(SECRET, path.read_text())
        self.assertNotIn('DO_NOT_SAVE_ENVELOPE', path.read_text())

    def test_disabled_capture_still_reports_code_without_writing_or_retry(self):
        model = self.model(capture=False)
        with patch('axiom.providers._transport', return_value=reply('{bad JSON')) as send, \
             patch.object(model, '_save_diagnostic', side_effect=AssertionError('Capture disabled')):
            with self.assertRaises(ValueError):
                model.complete('Synthetic request.', {}, DRAFT_SCHEMA)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(model.calls[0]['validation_error'], 'model_response_invalid_json')
        self.assertNotIn('diagnostic_file', model.calls[0])
        self.assertFalse(self.diag.exists())

    def test_schema_and_claim_identity_failures_have_specific_codes(self):
        cases = [({}, DRAFT_SCHEMA, {}, 'model_response_schema_missing_fields'),
                 (dict(RESULT, claims='wrong type'), DRAFT_SCHEMA, {}, 'model_response_schema_type'),
                 (dict(RESULT, extra='not allowed'), DRAFT_SCHEMA, {}, 'model_response_schema_extra_fields'),
                 ({'reviews': []}, BATCH_REVIEW_SCHEMA,
                  {'claims': [{'claim_id': 'claim-0', 'text': 'Synthetic claim.'}], 'evidence': self.evidence},
                  'review_claim_count_mismatch')]
        changed = self.review()
        changed['reviews'][0]['claim_id'] = 'unknown-id'
        cases.append((changed, BATCH_REVIEW_SCHEMA,
            {'claims': [{'claim_id': 'claim-0', 'text': 'Synthetic claim.'}], 'evidence': self.evidence},
            'review_claim_id_mismatch'))
        for result, schema, payload, code in cases:
            with self.subTest(code=code):
                model = self.model(capture=False)
                with patch('axiom.providers._transport', return_value=reply(json.dumps(result))) as send:
                    with self.assertRaises(ValueError):
                        model.complete('Synthetic request.', payload, schema)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(model.calls[0]['validation_error'], code)

    def test_unavailable_source_and_missing_support_are_not_softened(self):
        for mutation, code in [('source', 'review_source_mismatch'), ('supports', 'review_supporting_span_missing')]:
            result = self.review()
            if mutation == 'source':
                result['reviews'][0]['evidence_checks'][0]['source_id'] = 'another-source'
            else:
                result['reviews'][0]['evidence_checks'] = []
            model = self.model(capture=False)
            with self.subTest(code=code), patch('axiom.providers._transport', return_value=reply(json.dumps(result))):
                with self.assertRaises(ValueError):
                    model.review_many(['Synthetic claim.'], self.evidence)
            self.assertEqual(model.calls[0]['validation_error'], code)

    def test_direct_and_unicode_escaped_credentials_never_reach_diagnostic_disk(self):
        encoded_key = ''.join('\\u%04x' % ord(character) for character in SECRET)
        for content in [json.dumps({'echo': SECRET}), '{"echo":"' + encoded_key + '"}',
                        '{malformed:' + encoded_key]:
            with self.subTest(encoding=content[:15]):
                model = self.model()
                with patch('axiom.providers._transport', return_value=reply(content)) as send:
                    with self.assertRaises(ValueError) as error:
                        model.complete('Synthetic request.', {}, {})
                self.assertEqual(send.call_count, 1)
                self.assertEqual(model.calls[0]['validation_error'], 'model_response_sensitive_content')
                self.assertEqual(model.calls[0]['diagnostic_capture'], 'sensitive_content_omitted')
                self.assertEqual(list(self.diag.glob('*.json')), [])
                self.assertEqual(list(self.cache.glob('*.json')), [])
                self.assertNotIn(SECRET, str(error.exception) + json.dumps(model.calls))

    def test_oversized_rejected_text_keeps_only_bounded_metadata(self):
        for content, omission in [('x' * (MAX_DIAGNOSTIC_CONTENT_BYTES + 1), 'size_limit'),
                                  ('\x01' * MAX_DIAGNOSTIC_CONTENT_BYTES, 'encoded_size_limit')]:
            with self.subTest(omission=omission):
                model = self.model()
                with patch('axiom.providers._transport', return_value=reply(content)):
                    with self.assertRaises(ValueError):
                        model.complete('Synthetic request.', {}, DRAFT_SCHEMA)
                path, record = self.read_diagnostic()
                self.assertIsNone(record['untrusted_model_content'])
                self.assertEqual(record['content_omitted'], omission)
                self.assertEqual(record['model_content_bytes'], len(content.encode()))
                path.unlink()

    def test_valid_responses_keep_existing_cache_behavior_without_capture(self):
        model = self.model()
        with patch('axiom.providers._transport', return_value=reply(json.dumps(RESULT))) as send:
            self.assertEqual(model.complete('Synthetic request.', {}, DRAFT_SCHEMA), RESULT)
            self.assertEqual(model.complete('Synthetic request.', {}, DRAFT_SCHEMA), RESULT)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(model.calls[-1]['status'], 'cache_hit')
        self.assertFalse(self.diag.exists())

    def test_malformed_http_envelope_is_not_retained_as_model_text(self):
        model = self.model()
        with patch('axiom.providers._transport', return_value={'http_status': 200, 'body': 'NOT_MODEL_TEXT'}):
            with self.assertRaises(ValueError):
                model.complete('Synthetic request.', {}, DRAFT_SCHEMA)
        self.assertEqual(model.calls[0]['validation_error'], 'provider_response_envelope_invalid')
        self.assertEqual(model.calls[0]['diagnostic_capture'], 'model_content_unavailable')
        self.assertFalse(self.diag.exists())

    def test_capture_write_failure_never_changes_the_original_rejection(self):
        model = self.model()
        with patch('axiom.providers._transport', return_value=reply('{bad JSON')), \
             patch('axiom.providers.tempfile.NamedTemporaryFile', side_effect=PermissionError('DO_NOT_LOG_THIS')):
            with self.assertRaisesRegex(ValueError, 'invalid_response') as error:
                model.complete('Synthetic request.', {}, DRAFT_SCHEMA)
        self.assertEqual(model.calls[0]['diagnostic_capture'], 'write_failed')
        self.assertEqual(model.calls[0]['validation_error'], 'model_response_invalid_json')
        self.assertNotIn('DO_NOT_LOG_THIS', str(error.exception) + json.dumps(model.calls))
        self.assertEqual(list(self.diag.glob('*.json')), [])

    def test_invalid_metadata_cannot_choose_a_capture_path_or_reason(self):
        model = self.model()
        event = {'request_hash': '../outside', 'schema_hash': 'a' * 64, 'prompt_hash': 'b' * 64, 'attempt': 1}
        result = model._save_diagnostic(event, '{bad', 'model_json', 'model_response_invalid_json')
        self.assertEqual(result['diagnostic_capture'], 'metadata_invalid')
        self.assertFalse(self.diag.exists())
        event['request_hash'] = 'c' * 64
        result = model._save_diagnostic(event, '{bad', 'model_json', SECRET)
        self.assertEqual(result['diagnostic_capture'], 'metadata_invalid')

    def test_existing_non_directory_or_redirected_capture_root_is_refused(self):
        self.diag.write_text('Existing non-directory', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'directory'):
            self.model()
        self.diag.unlink()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        try:
            self.diag.symlink_to(elsewhere, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable on this host')
        with self.assertRaisesRegex(ValueError, 'redirects'):
            self.model()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_explicit_factory_capture_option_does_not_enable_default_retention(self):
        with patch('axiom.providers.settings', return_value={'GROQ_KEY': SECRET}):
            self.assertIsNone(make_model(self.root).diagnostics_dir)
            self.assertEqual(make_model(self.root, diagnostics_dir=self.diag).diagnostics_dir, self.diag.absolute())


if __name__ == '__main__':
    unittest.main()
