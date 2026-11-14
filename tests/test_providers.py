"""Hosted adapter tests use simulated provider responses and local child processes."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from axiom.model import DRAFT_SCHEMA
from axiom.providers import HostedModel, _digest, _http_worker, _retry_seconds, _reset_seconds, _rate_headers, _transport, make_model
from axiom.provider_limits import Limiter


SECRET = 'fixture-secret-not-for-disk'
RESULT = {'claims': [], 'abstained': True, 'reason': 'Synthetic abstention'}


class Clock:
    def __init__(self):
        self.value = 100.0
        self.waits = []
    def now(self):
        return self.value
    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds


def reply(content='{}', finish='stop', usage=None):
    envelope = {'model': 'fixture/model', 'choices': [{'finish_reason': finish, 'message': {'content': content}}],
                'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10} if usage is None else usage}
    return {'http_status': 200, 'body': json.dumps(envelope)}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=os.environ.get('AXIOM_TEST_TMPDIR'))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cache = self.root / 'cache'
        pacing = patch('axiom.providers.shared_limiter', side_effect=lambda *args: Limiter(min_interval=0))
        pacing.start()
        self.addCleanup(pacing.stop)

    def model(self, cache=False, timeout=3, limiter=None, max_attempts=4):
        return HostedModel('groq', 'fixture-model', SECRET, timeout=timeout, cache_dir=self.cache if cache else None,
                           limiter=limiter, max_attempts=max_attempts)

    def test_paid_openrouter_blocked(self):
        with self.assertRaises(ValueError):
            HostedModel('openrouter', 'paid/model', SECRET)

    def test_missing_key(self):
        with self.assertRaises(ValueError):
            HostedModel('groq', 'model', None)

    def test_extractive_needs_no_key(self):
        self.assertIsNone(make_model(self.root, 'extractive'))

    def test_json_parse_and_audit_excludes_key(self):
        model = self.model()
        with patch('axiom.providers._transport', return_value=reply('{"ok":true}')):
            self.assertEqual(model.complete('instruction', {}, {}), {'ok': True})
        audit = model.calls[0]
        self.assertEqual(audit['status'], 'success')
        self.assertEqual(audit['usage']['total_tokens'], 10)
        for name in ('prompt_hash', 'schema_hash', 'request_hash', 'output_hash'):
            self.assertRegex(audit[name], r'^[a-f0-9]{64}$')
        self.assertNotIn(SECRET, json.dumps(audit))

    def test_nemotron_aliases_and_capabilities(self):
        for alias, expected_format in [('nemotron-ultra', False), ('nemotron-super-vl', True)]:
            model = HostedModel('openrouter', alias, SECRET)
            self.assertTrue(model.name.endswith(':free'))
            with patch('axiom.providers._transport', return_value=reply()) as transport:
                model.complete('test', {}, {})
            body = transport.call_args.args[2]
            self.assertEqual('response_format' in body, expected_format)
            self.assertEqual(body['provider']['max_price'], {'prompt': 0, 'completion': 0})
            self.assertFalse(body['provider']['allow_fallbacks'])

    def test_cache_replays_only_valid_response_without_transport_or_extra_tokens(self):
        model = self.model(cache=True)
        with patch('axiom.providers._transport', return_value=reply(json.dumps(RESULT))):
            self.assertEqual(model.draft('Fixture question?', []), RESULT)
        replay = self.model(cache=True)
        with patch('axiom.providers._transport', side_effect=AssertionError('Cache should avoid transport')):
            self.assertEqual(replay.draft('Fixture question?', []), RESULT)
        self.assertTrue(replay.calls[0]['cache_hit'])
        self.assertEqual(replay.calls[0]['usage']['total_tokens'], 0)
        self.assertEqual(replay.calls[0]['cached_usage']['total_tokens'], 10)
        files = list(self.cache.iterdir())
        self.assertEqual(len(files), 1)
        self.assertNotIn(SECRET, files[0].read_text(encoding='utf-8'))
        self.assertNotIn('Fixture question?', files[0].read_text(encoding='utf-8'))

    def test_cache_identity_includes_provider_model_prompt_and_schema(self):
        models = [self.model(cache=True), HostedModel('groq', 'other-model', SECRET, cache_dir=self.cache),
                  HostedModel('openrouter', 'fixture:free', SECRET, cache_dir=self.cache)]
        calls = [(models[0], 'first', {}, {}), (models[0], 'second', {}, {}),
                 (models[0], 'first', {'different': True}, {}), (models[0], 'first', {}, {'type': 'object'}),
                 (models[1], 'first', {}, {}), (models[2], 'first', {}, {})]
        with patch('axiom.providers._transport', return_value=reply()) as transport:
            for model, system, payload, schema in calls:
                model.complete(system, payload, schema)
            self.assertEqual(transport.call_count, len(calls))
        self.assertEqual(len(set(event['request_hash'] for m in models for event in m.calls)), len(calls))

    def test_invalid_json_wrong_schema_and_truncation_preserve_usage_and_do_not_cache(self):
        for response, status in [(reply('{' ), 'invalid_response'), (reply('{"answer":true}'), 'invalid_response'),
                                 (reply(json.dumps(RESULT), finish='length'), 'incomplete')]:
            with self.subTest(status=status):
                model = self.model(cache=True)
                with patch('axiom.providers._transport', side_effect=[response, reply(json.dumps(RESULT))]) as transport:
                    with self.assertRaises(ValueError):
                        model.complete('fixture', {}, DRAFT_SCHEMA)
                    self.assertEqual(model.calls[0]['status'], status)
                    self.assertEqual(model.calls[0]['usage']['total_tokens'], 10)
                    self.assertEqual(list(self.cache.glob('*.json')), [])
                    self.assertEqual(model.complete('fixture', {}, DRAFT_SCHEMA), RESULT)
                    self.assertEqual(transport.call_count, 2)
                for file in self.cache.glob('*.json'):
                    file.unlink()

    def test_secret_echo_never_persisted_or_logged(self):
        model = self.model(cache=True)
        with patch('axiom.providers._transport', return_value=reply(json.dumps({'echo': SECRET}))):
            with self.assertRaises(ValueError) as exc:
                model.complete('fixture', {}, {})
        self.assertNotIn(SECRET, str(exc.exception))
        self.assertNotIn(SECRET, json.dumps(model.calls))
        self.assertEqual(list(self.cache.glob('*.json')), [])

    def test_corrupt_cache_refetched_then_atomically_replaced(self):
        model = self.model(cache=True)
        with patch('axiom.providers._transport', return_value=reply()) as transport:
            model.complete('fixture', {}, {})
            file, = self.cache.glob('*.json')
            file.write_text('{truncated', encoding='utf-8')
            self.assertEqual(model.complete('fixture', {}, {}), {})
            self.assertEqual(transport.call_count, 2)
        self.assertEqual(json.loads(file.read_text(encoding='utf-8'))['result'], {})
        self.assertEqual(list(self.cache.glob('*.tmp')), [])

    def test_forged_review_span_is_rejected_before_cache_storage(self):
        chunks = [{'source_id': 'fixture-source', 'chunk_id': 'fixture-chunk',
                   'text': 'The synthetic sample burned.'}]
        forged = {'verdict': 'contradicted', 'reason': 'Synthetic explanation.',
                  'evidence_checks': [{'source_id': 'fixture-source', 'chunk_id': 'fixture-chunk',
                                       'quote': 'The synthetic sample did not burn.', 'relation': 'contradicts'}],
                  'uncertainty': 'Fixture scope only.'}
        model = self.model(cache=True)
        with patch('axiom.providers._transport', return_value=reply(json.dumps(forged))) as transport:
            with self.assertRaisesRegex(ValueError, 'invalid_response'):
                model.review('The synthetic sample burned.', chunks)
        transport.assert_called_once()
        self.assertEqual(model.calls[0]['status'], 'invalid_response')
        self.assertEqual(list(self.cache.glob('*.json')), [])

    def test_old_forged_review_cache_is_ignored_and_fresh_raw_review_is_preserved(self):
        chunks = [{'source_id': 'fixture-source', 'chunk_id': 'fixture-chunk',
                   'text': 'The synthetic sample burned. Evidence is limited to this setup.'}]
        valid = {'verdict': 'supported', 'reason': 'Synthetic explanation.',
                 'evidence_checks': [
                     {'source_id': 'fixture-source', 'chunk_id': 'fixture-chunk',
                      'quote': 'The synthetic sample burned.', 'relation': 'supports'},
                     {'source_id': 'fixture-source', 'chunk_id': 'fixture-chunk',
                      'quote': 'Evidence is limited to this setup.', 'relation': 'limits'}],
                 'uncertainty': 'Fixture scope only.'}
        model = self.model(cache=True)
        with patch('axiom.providers._transport', return_value=reply(json.dumps(valid))):
            normalized = model.review('The synthetic sample burned.', chunks)
        self.assertEqual(normalized['verdict'], 'uncertain')
        self.assertEqual(normalized['asserted_verdict'], 'supported')
        file, = self.cache.glob('*.json')
        entry = json.loads(file.read_text(encoding='utf-8'))
        self.assertEqual(entry['result'], valid)
        entry['result']['evidence_checks'][0]['quote'] = 'Forged historical span.'
        entry['result_sha256'] = _digest(entry['result'])
        file.write_text(json.dumps(entry), encoding='utf-8')
        replay = self.model(cache=True)
        with patch('axiom.providers._transport', return_value=reply(json.dumps(valid))) as transport:
            fresh = replay.review('The synthetic sample burned.', chunks)
        transport.assert_called_once()
        self.assertFalse(replay.calls[0]['cache_hit'])
        self.assertEqual(fresh['verdict'], 'uncertain')
        self.assertEqual(json.loads(file.read_text(encoding='utf-8'))['result'], valid)

    def test_actual_six_second_cooldown_recovers_without_early_retry(self):
        clock = Clock()
        model = self.model(timeout=20,limiter=Limiter(0,clock=clock.now,sleep=clock.sleep))
        times = []
        replies = iter([{'http_status':429,'retry_after_s':6.0}, reply()])
        def transport(*args):
            times.append(clock.now())
            return next(replies)
        with patch('axiom.providers._transport',side_effect=transport), \
             patch('axiom.providers.time.monotonic',clock.now), patch('axiom.providers.random.uniform',return_value=0):
            self.assertEqual(model.complete('fixture',{},{}),{})
        self.assertEqual(times,[100,106])
        self.assertEqual([call['status'] for call in model.calls],['rate_limited','success'])
        self.assertEqual(model.calls[0]['retry_delay_s'],6)
        self.assertEqual(model.calls[1]['queue_wait_ms'],6000)
        self.assertLessEqual(max(clock.waits),.25)

    def test_retries_are_bounded_and_never_early_for_long_cooldown(self):
        for codes,count in [([{'http_status':429,'retry_after_s':60}],1),
                            ([{'http_status':429,'retry_after_s':0}]*4,4), ([{'http_status':401}],1)]:
            clock=Clock()
            model=self.model(timeout=20,limiter=Limiter(0,clock=clock.now,sleep=clock.sleep))
            with patch('axiom.providers._transport',side_effect=codes) as transport, \
                 patch('axiom.providers.time.monotonic',clock.now),patch('axiom.providers.random.uniform',return_value=0):
                with self.assertRaises(ValueError):model.complete('fixture',{}, {})
                self.assertEqual(transport.call_count,count)
            self.assertLessEqual(clock.now(),120)

    def test_missing_quota_cooldown_fails_with_no_transport_and_cache_bypasses_queue(self):
        clock=Clock()
        limiter=Limiter(0,clock=clock.now,sleep=clock.sleep)
        model=self.model(cache=True,timeout=3,limiter=limiter)
        with patch('axiom.providers._transport',return_value=reply()),patch('axiom.providers.time.monotonic',clock.now):
            self.assertEqual(model.complete('fixture',{},{}),{})
        limiter.observe(limits={'remaining_requests':0,'reset_requests_s':3600})
        with patch('axiom.providers._transport') as transport,patch('axiom.providers.time.monotonic',clock.now):
            self.assertEqual(model.complete('fixture',{},{}),{})
            with self.assertRaisesRegex(ValueError,'waiting for quota'):
                model.complete('different fixture',{}, {})
            transport.assert_not_called()
        self.assertEqual(model.calls[-1]['status'],'cooldown_exceeded')
        self.assertFalse(model.calls[-1]['transport_attempted'])

    def test_retryable_service_outage_uses_backoff_and_preserves_attempts(self):
        clock=Clock()
        model=self.model(timeout=20,limiter=Limiter(0,clock=clock.now,sleep=clock.sleep))
        with patch('axiom.providers._transport',side_effect=[{'http_status':503},reply()]), \
             patch('axiom.providers.time.monotonic',clock.now),patch('axiom.providers.random.uniform',return_value=0):
            self.assertEqual(model.complete('fixture',{},{}),{})
        self.assertEqual(clock.now(),101)
        self.assertEqual([call['status'] for call in model.calls],['retryable_http_error','success'])

    def test_reset_header_parser_and_metadata_allowlist(self):
        for text,expected in [('7.66s',7.66),('2m59.56s',179.56),('1h2m3s',3723),('250ms',.25)]:
            self.assertAlmostEqual(_reset_seconds(text),expected)
        for text in (None,'nan','inf','-1','garbage','1m invalid',True):
            self.assertIsNone(_reset_seconds(text))
        limits=_rate_headers({'x-ratelimit-remaining-requests':'12','x-ratelimit-remaining-tokens':'0',
                             'x-ratelimit-reset-tokens':'7.66s','Authorization':SECRET,'x-private':SECRET})
        self.assertEqual(limits,{'remaining_requests':12,'remaining_tokens':0,'reset_tokens_s':7.66})
        self.assertNotIn(SECRET,json.dumps(limits))

    def test_retry_after_parser_and_worker_never_reads_http_error_body(self):
        self.assertEqual(_retry_seconds('3'), 3)
        self.assertEqual(_retry_seconds('Sun, 01 Jan 1995 00:00:00 GMT'), 0)
        self.assertEqual(_retry_seconds('malformed'), 2)
        body = MagicMock(wraps=io.BytesIO(b'sensitive error body'))
        http_error = urllib.error.HTTPError('https://example.invalid', 429, 'rate limited', {'Retry-After': '4'}, body)
        with patch('axiom.providers.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = http_error
            result = _http_worker({'provider': 'groq', 'key': SECRET, 'body': {}, 'remaining': 30})
        self.assertEqual(result, {'http_status': 429, 'retry_after_s': 4.0,'rate_limits':{}})
        body.read.assert_not_called()
        self.assertLessEqual(opener.return_value.open.call_args.kwargs['timeout'], 15)

    def test_wall_deadline_kills_stalling_local_worker(self):
        # The stand-in never opens a network connection. The actual parent
        # transport must return before this child's four-second sleep completes.
        stalled = [sys.executable, '-c', 'import sys,time; sys.stdin.buffer.read(); time.sleep(4)']
        model = self.model(timeout=0.20)
        started = time.monotonic()
        with patch('axiom.providers.WORKER_COMMAND', stalled), self.assertRaisesRegex(ValueError, 'wall deadline'):
            model.complete('fixture', {}, {})
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(model.calls[0]['status'], 'timeout')
        self.assertEqual(model.calls[0]['usage'], {})

    def test_transport_keeps_credentials_out_of_command_and_suppresses_stderr(self):
        completed = subprocess.CompletedProcess([], 0, stdout=b'{"http_status":401}')
        with patch('axiom.providers.subprocess.run', return_value=completed) as run:
            self.assertEqual(_transport('groq', SECRET, {}, 1.5), {'http_status': 401})
        args, kwargs = run.call_args
        self.assertNotIn(SECRET, repr(args))
        self.assertEqual(json.loads(kwargs['input'])['key'], SECRET)
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
        self.assertEqual(kwargs['timeout'], 1.5)

    def test_make_model_cache_path_and_opt_out(self):
        with patch('axiom.providers.settings', return_value={'GROQ_KEY': SECRET}):
            self.assertEqual(make_model(self.root).cache_dir, self.root / 'runs/model_cache')
            self.assertIsNone(make_model(self.root, use_cache=False).cache_dir)

    def test_grouped_review_cache_verifies_each_span_before_replay(self):
        chunks=[{'source_id':'fixture-source','chunk_id':'fixture-chunk','text':'The synthetic sample burned under the fixture conditions.'}]
        row={'claim_id':'claim-0','verdict':'supported','reason':'Fixture support.',
             'evidence_checks':[{'source_id':'fixture-source','chunk_id':'fixture-chunk','quote':chunks[0]['text'],'relation':'supports'}],
             'uncertainty':'Fixture scope only.'}
        result={'reviews':[row]}
        model=self.model(cache=True)
        with patch('axiom.providers._transport',return_value=reply(json.dumps(result))) as transport:
            self.assertEqual(model.review_many(['Fixture observation'],chunks)[0]['verdict'],'supported')
            self.assertEqual(model.review_many(['Fixture observation'],chunks)[0]['verdict'],'supported')
        transport.assert_called_once()
        self.assertTrue(model.calls[-1]['cache_hit'])
        self.assertEqual(model.calls[-1]['usage']['total_tokens'],0)
        row['evidence_checks'][0]['quote']='An invented supporting quotation.'
        with patch('axiom.providers._transport',return_value=reply(json.dumps(result))):
            with self.assertRaises(ValueError):
                model.review_many(['A different fixture claim'],chunks)
        self.assertEqual(len(list(self.cache.glob('*.json'))),1)
