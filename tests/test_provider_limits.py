from concurrent.futures import ThreadPoolExecutor
import threading
import time
import unittest

from axiom.provider_limits import Limiter, shared_limiter


class Clock:
    def __init__(self):
        self.current = 100.0
        self.sleeps = []

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.current += seconds


class ProviderLimitTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()

    def limiter(self, interval=0):
        return Limiter(interval, clock=self.clock.now, sleep=self.clock.sleep)

    def test_interval_exposed_read_only_for_provider_audit(self):
        limiter = self.limiter(0.75)
        self.assertEqual(limiter.min_interval, 0.75)
        with self.assertRaises(AttributeError):
            limiter.min_interval = 0

    def test_registry_shares_only_matching_provider_model_and_key(self):
        identity = ('provider-a', 'model-a', 'synthetic-fake-secret')
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: shared_limiter(*identity), range(12)))
        self.assertTrue(all(value is values[0] for value in values))
        for alternate in [('provider-b', identity[1], identity[2]),
                          (identity[0], 'model-b', identity[2]),
                          (identity[0], identity[1], 'another-fake-key')]:
            self.assertIsNot(values[0], shared_limiter(*alternate))
        self.assertNotIn(identity[2], repr(vars(values[0])))

    def test_default_interval_spaces_starts_and_counts_elapsed_transport(self):
        limiter = Limiter(clock=self.clock.now, sleep=self.clock.sleep)
        with limiter.slot(110) as first:
            self.assertEqual(first, 0)
            self.clock.current += 0.5
        with limiter.slot(110) as second:
            self.assertAlmostEqual(second, 1.5)
            self.assertAlmostEqual(self.clock.now(), 102)
        self.assertTrue(all(0 < duration <= 0.25 for duration in self.clock.sleeps))

    def test_retry_after_and_exhausted_quota_windows_use_longest_delay(self):
        limiter = self.limiter()
        with limiter.slot(200):
            limiter.observe(retry_after_s=3, limits={'remaining_requests': 0, 'reset_requests_s': 8,
                                                   'remaining_tokens': 0, 'reset_tokens_s': 4})
        self.clock.current += 1
        limiter.observe(retry_after_s=0.5)
        limiter.observe(limits={'remaining_requests': 9, 'remaining_tokens': 20})
        with limiter.slot(200) as waited:
            self.assertEqual(waited, 7)
            self.assertEqual(self.clock.now(), 108)

    def test_positive_remaining_counts_do_not_trigger_resets(self):
        limiter = self.limiter()
        limiter.observe(limits={'remaining_requests': 1, 'reset_requests_s': 86000,
                                'remaining_tokens': 750, 'reset_tokens_s': 59})
        with limiter.slot(101) as waited:
            self.assertEqual(waited, 0)
        self.assertEqual(self.clock.sleeps, [])

    def test_token_reset_applies_independently_of_request_budget(self):
        limiter = self.limiter()
        limiter.observe(limits={'remaining_tokens': 0, 'reset_tokens_s': 1.5,
                                'remaining_requests': 50, 'reset_requests_s': 999})
        with limiter.slot(103) as waited:
            self.assertEqual(waited, 1.5)

    def test_short_deadline_cannot_bypass_cooldown_or_poison_gate(self):
        limiter = self.limiter()
        limiter.observe(retry_after_s=10)
        with self.assertRaises(TimeoutError), limiter.slot(101):
            self.fail('Slot was granted during cooldown')
        with self.assertRaises(TimeoutError), limiter.slot(110):
            self.fail('Slot was granted at the deadline')
        with limiter.slot(120):
            self.assertGreaterEqual(self.clock.now(), 110)

    def test_future_observation_extends_waiting_slot(self):
        def extend_during_sleep(seconds):
            self.clock.sleep(seconds)
            if len(self.clock.sleeps) == 1:
                limiter.observe(retry_after_s=3)

        limiter = Limiter(0, clock=self.clock.now, sleep=extend_during_sleep)
        limiter.observe(retry_after_s=1)
        with limiter.slot(110) as waited:
            self.assertEqual(waited, 3.25)

    def test_ignores_malformed_optional_observations(self):
        limiter = self.limiter()
        for candidate in ('1', False, -1, float('nan'), float('inf'), 10 ** 400):
            with self.subTest(candidate=str(candidate)[:10]):
                limiter.observe(retry_after_s=candidate,
                                limits={'remaining_requests': candidate, 'reset_requests_s': 1000,
                                        'remaining_tokens': 0, 'reset_tokens_s': candidate})
        with limiter.slot(101) as waited:
            self.assertEqual(waited, 0)

    def test_user_interrupt_releases_gate_and_preserves_original_cooldown(self):
        interrupted = False
        def interrupt_once(seconds):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
            self.clock.sleep(seconds)

        limiter = Limiter(0, clock=self.clock.now, sleep=interrupt_once)
        limiter.observe(retry_after_s=1)
        with self.assertRaises(KeyboardInterrupt), limiter.slot(110):
            self.fail('Interrupted wait unexpectedly acquired a slot')
        with limiter.slot(110) as waited:
            self.assertEqual(waited, 1)

    def test_one_live_request_at_a_time_and_deadline_includes_queue(self):
        limiter = Limiter(0)
        entered = threading.Event()
        release = threading.Event()
        def worker():
            with limiter.slot(time.monotonic() + 1):
                entered.set()
                release.wait(1)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaises(TimeoutError), limiter.slot(time.monotonic() + 0.03):
                    self.fail('Concurrent request entered before active request exited')
            finally:
                release.set()
            future.result(timeout=1)
        with limiter.slot(time.monotonic() + 1):
            pass

    def test_raised_transport_error_releases_gate(self):
        limiter = self.limiter()
        with self.assertRaises(OSError), limiter.slot(110):
            raise OSError('Synthetic transport failure')
        with limiter.slot(110) as waited:
            self.assertEqual(waited, 0)


if __name__ == '__main__':
    unittest.main()
