"""Serialize requests and share observed quota cooldowns within one process."""
from contextlib import contextmanager
import hashlib
import math
from threading import Lock
import time


POLL_SECONDS = 0.25


def _duration(value):
    """Return a finite, nonnegative duration from normalized numeric metadata."""
    if type(value) not in (int, float):
        return None
    try:
        if value >= 0 and math.isfinite(value):
            return float(value)
    except OverflowError:
        pass
    return None


class Limiter:
    def __init__(self, min_interval=2.0, *, clock=None, sleep=None):
        interval = _duration(min_interval)
        if interval is None:
            raise ValueError('Minimum request interval must be finite and nonnegative')
        self._interval = interval
        self._now = time.monotonic if clock is None else clock
        self._sleep = time.sleep if sleep is None else sleep
        self._gate = Lock()
        self._state = Lock()
        self._next_start = float('-inf')

    @property
    def min_interval(self):
        """Minimum spacing between request starts, in seconds."""
        return self._interval

    @contextmanager
    def slot(self, deadline):
        """Hold a request slot until transport and rate-limit observation finish.

        The absolute monotonic deadline covers both the queue and cooldown.
        The caller enforces the remaining deadline during its own transport.
        """
        if _duration(deadline) is None:
            raise ValueError('Request deadline must be finite and nonnegative')
        started = self._now()
        while True:
            remaining = deadline - self._now()
            if remaining <= 0:
                raise TimeoutError('Request deadline expired while waiting for a provider slot')
            if self._gate.acquire(timeout=min(POLL_SECONDS, remaining)):
                break
        try:
            while True:
                with self._state:
                    now = self._now()
                    if now >= deadline or self._next_start >= deadline:
                        raise TimeoutError('Provider cooldown exceeds the request deadline')
                    delay = self._next_start - now
                    if delay <= 0:
                        self._next_start = now + self._interval
                        break
                # Another observer may extend the cooldown while this slot waits.
                self._sleep(min(POLL_SECONDS, delay))
            yield now - started
        finally:
            self._gate.release()

    def observe(self, retry_after_s=None, limits=None):
        """Extend the cooldown from Retry-After and exhausted quota windows."""
        delay = _duration(retry_after_s) or 0.0
        if isinstance(limits, dict):
            for quota in ('requests', 'tokens'):
                remaining = _duration(limits.get('remaining_' + quota))
                if remaining == 0:
                    reset = _duration(limits.get('reset_' + quota + '_s'))
                    if reset is not None:
                        delay = max(delay, reset)
        if delay:
            with self._state:
                self._next_start = max(self._next_start, self._now() + delay)


_registry = {}
_registry_lock = Lock()


def shared_limiter(provider, model, key):
    """Return the process-wide limiter for this provider, model and credential."""
    if any(not isinstance(value, str) or not value.strip() for value in (provider, model, key)):
        raise ValueError('Provider, model and credential must be nonempty strings')
    identity = (provider, model, hashlib.sha256(key.encode('utf-8')).digest())
    with _registry_lock:
        limiter = _registry.get(identity)
        if limiter is None:
            limiter = _registry[identity] = Limiter()
        return limiter
