"""Synthetic transport failures exercise classification and bounded retries."""
import errno
import json
import socket
import ssl
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from axiom.provider_limits import Limiter
from axiom.providers import HostedModel, _http_worker, RedirectRefused, TRANSIENT_TRANSPORT_ERRORS


SECRET = 'synthetic-transport-secret-never-log'


class Clock:
    def __init__(self):
        self.value = 100.0
    def now(self):
        return self.value
    def sleep(self, seconds):
        self.value += seconds


def response(content='{}'):
    return {'http_status': 200, 'body': json.dumps({'model': 'fixture', 'choices': [
        {'finish_reason': 'stop', 'message': {'content': content}}],
        'usage': {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7}})}


class ProviderTransportTests(unittest.TestCase):
    def model(self, clock, timeout=60):
        return HostedModel('groq', 'fixture', SECRET, timeout=timeout,
                           limiter=Limiter(0, clock=clock.now, sleep=clock.sleep))

    def worker_error(self, exception):
        with patch('axiom.providers.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = exception
            result = _http_worker({'provider': 'groq', 'key': SECRET, 'body': {}, 'remaining': 60})
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'], 15)
        self.assertNotIn(SECRET, json.dumps(result))
        return result

    def test_direct_and_wrapped_socket_timeouts_are_classified_without_strings(self):
        for error in (TimeoutError(SECRET), socket.timeout(SECRET),
                      urllib.error.URLError(TimeoutError(SECRET)),
                      urllib.error.URLError(OSError(errno.ETIMEDOUT, SECRET))):
            with self.subTest(error_type=type(error).__name__):
                self.assertEqual(self.worker_error(error), {'error': 'socket_timeout'})

    def test_explicit_connection_errors_and_temporary_dns_are_classified(self):
        for exception, category in (
            (ConnectionResetError(SECRET), 'connection_reset'),
            (urllib.error.URLError(ConnectionAbortedError(SECRET)), 'connection_aborted'),
            (ConnectionRefusedError(SECRET), 'connection_refused'),
            (BrokenPipeError(SECRET), 'connection_reset'),
            (urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, SECRET)), 'dns_temporary')):
            with self.subTest(category=category):
                self.assertEqual(self.worker_error(exception), {'error': category})

    def test_certificate_tls_redirect_and_unknown_failures_are_terminal_categories(self):
        for exception, category in (
            (ssl.SSLCertVerificationError(1, SECRET), 'certificate_error'),
            (urllib.error.URLError(ssl.SSLCertVerificationError(1, SECRET)), 'certificate_error'),
            (ssl.SSLError(1, SECRET), 'tls_error'),
            (RedirectRefused(SECRET), 'redirect_refused'),
            (urllib.error.URLError(SECRET), 'transport_failed'),
            (ValueError(SECRET), 'transport_failed'),
            (socket.gaierror(socket.EAI_NONAME, SECRET), 'dns_error')):
            with self.subTest(category=category):
                self.assertEqual(self.worker_error(exception), {'error': category})

    def test_invalid_response_encoding_and_size_never_export_body(self):
        for blob, category in ((b'\xff', 'invalid_encoding'), (b'x' * 2_000_001, 'response_size_limit')):
            with patch('axiom.providers.urllib.request.build_opener') as opener:
                http = MagicMock()
                http.headers = {}
                http.read.return_value = blob
                opener.return_value.open.return_value.__enter__.return_value = http
                result = _http_worker({'provider': 'groq', 'key': SECRET, 'body': {}, 'remaining': 60})
            self.assertEqual(result, {'error': category})

    def test_confirmed_transient_then_success_retries_with_unknown_failure_usage(self):
        clock = Clock()
        model = self.model(clock)
        def transport(*_):
            if not model.calls:
                clock.value += 15
                return {'error': 'socket_timeout'}
            return response()
        with patch('axiom.providers._transport', side_effect=transport) as send, \
             patch('axiom.providers.time.monotonic', clock.now), \
             patch('axiom.providers.random.uniform', return_value=0):
            self.assertEqual(model.complete('synthetic', {}, {}), {})
        self.assertEqual(send.call_count, 2)
        self.assertEqual(clock.now(), 116)
        self.assertEqual([call['status'] for call in model.calls], ['retryable_transport_error', 'success'])
        self.assertEqual(model.calls[0]['transport_error'], 'socket_timeout')
        self.assertEqual(model.calls[0]['usage'], {})
        self.assertTrue(model.calls[0]['retry_scheduled'])
        self.assertNotIn(SECRET, json.dumps(model.calls))

    def test_every_allowlisted_transient_retries_but_other_codes_never_do(self):
        for category in TRANSIENT_TRANSPORT_ERRORS:
            with self.subTest(category=category):
                clock = Clock()
                model = self.model(clock)
                with patch('axiom.providers._transport', side_effect=[{'error': category}, response()]) as send, \
                     patch('axiom.providers.time.monotonic', clock.now), \
                     patch('axiom.providers.random.uniform', return_value=0):
                    self.assertEqual(model.complete('synthetic', {}, {}), {})
                self.assertEqual(send.call_count, 2)
        for category in ('certificate_error', 'tls_error', 'dns_error', 'redirect_refused', 'invalid_encoding',
                         'response_size_limit', 'transport_failed', 'parent_deadline_exceeded', SECRET):
            with self.subTest(category=category):
                clock = Clock()
                model = self.model(clock)
                with patch('axiom.providers._transport', return_value={'error': category}) as send, \
                     patch('axiom.providers.time.monotonic', clock.now), self.assertRaises(ValueError) as caught:
                    model.complete('synthetic', {}, {})
                self.assertEqual(send.call_count, 1)
                self.assertEqual(model.calls[0]['status'], 'transport_failed')
                self.assertNotIn(SECRET, str(caught.exception) + json.dumps(model.calls))

    def test_deadline_exhaustion_prevents_another_transport(self):
        clock = Clock()
        model = self.model(clock)
        def transport(*_):
            clock.value += 59.5
            return {'error': 'socket_timeout'}
        with patch('axiom.providers._transport', side_effect=transport) as send, \
             patch('axiom.providers.time.monotonic', clock.now), \
             patch('axiom.providers.random.uniform', return_value=0), self.assertRaisesRegex(ValueError, 'budget exhausted'):
            model.complete('synthetic', {}, {})
        self.assertEqual(send.call_count, 1)
        self.assertFalse(model.calls[0]['retry_scheduled'])
        self.assertLessEqual(clock.now() - 100, 60)

    def test_four_attempt_limit_and_backoff_stay_inside_total_deadline(self):
        clock = Clock()
        model = self.model(clock)
        with patch('axiom.providers._transport', return_value={'error': 'connection_reset'}) as send, \
             patch('axiom.providers.time.monotonic', clock.now), \
             patch('axiom.providers.random.uniform', return_value=0), self.assertRaises(ValueError):
            model.complete('synthetic', {}, {})
        self.assertEqual(send.call_count, 4)
        self.assertEqual(clock.now(), 107)
        self.assertFalse(model.calls[-1]['retry_scheduled'])
        self.assertEqual(model.retry_policy['max_attempts'], 4)
        self.assertEqual(model.retry_policy['total_deadline_s'], 60)
        self.assertEqual(model.retry_policy['socket_idle_timeout_s'], 15)
        self.assertEqual(set(model.retry_policy['retry_transport_errors']), TRANSIENT_TRANSPORT_ERRORS)

    def test_parent_deadline_is_terminal_and_diagnosed(self):
        clock = Clock()
        model = self.model(clock)
        with patch('axiom.providers._transport', side_effect=TimeoutError(SECRET)) as send, \
             patch('axiom.providers.time.monotonic', clock.now), self.assertRaisesRegex(ValueError, 'wall deadline') as caught:
            model.complete('synthetic', {}, {})
        self.assertEqual(send.call_count, 1)
        self.assertEqual(model.calls[0]['transport_error'], 'parent_deadline_exceeded')
        self.assertEqual(model.calls[0]['status'], 'timeout')
        self.assertNotIn(SECRET, str(caught.exception) + json.dumps(model.calls))

    def test_invalid_json_and_schema_do_not_retry_as_network_errors(self):
        for content in ('invalid ' + SECRET, '[]', '{"claims":[]}'):
            with self.subTest(content_kind=content[:8]):
                clock = Clock()
                model = self.model(clock)
                schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                          'required': ['ok'], 'additionalProperties': False}
                with patch('axiom.providers._transport', return_value=response(content)) as send, \
                     patch('axiom.providers.time.monotonic', clock.now), self.assertRaises(ValueError) as caught:
                    model.complete('synthetic', {}, schema)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(model.calls[0]['status'], 'invalid_response')
                self.assertNotIn(SECRET, str(caught.exception) + json.dumps(model.calls))


if __name__ == '__main__':
    unittest.main()
