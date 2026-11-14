# Hosted-provider recovery · November 5, 2026

**Phase 6C extension, November 6:** safe, allowlisted transport categories now
distinguish confirmed transient socket/network failures from terminal TLS,
certificate, encoding, redirect, size and unknown errors. Transient failures use
bounded backoff within four attempts and the nominal 60-second total budget.
The 15-second socket idle cap remains. Actual recovery Q018/baseline recorded a
socket timeout followed by success. Scientific output validation remains terminal.

The original run also recorded a 985,750ms cooldown/deadline overrun. Its cause
is unknown; the configured limit must not be reported as a measured maximum.
No exception text or HTTP error bodies are logged, and usage after failed
transport remains unknown. [Phase 6C observations and full run history](history/PHASE6C_STATUS.md)

**November 6 live checkpoint:** Phase 6B pilot
`a96001f691e547fe93a3f03a54a86603` completed nine workflows without failure.
Its provider records contain nine successful calls and three rate-limited
attempts, with no cache hits. This supplies a live recovery observation alongside
the original simulated six-second regression. It does not guarantee capacity
under another quota or make the answers scientifically validated. See
[the pilot record](history/PHASE6B_STATUS.md).

The Phase 6 failure was HTTP 429 with `retry_after_s: 6`. The former client
allowed only waits up to five seconds, so it stopped before attempting recovery.
This was a client policy failure, not evidence of a failed scientific check.

## Current behavior

- Up to four total HTTP attempts for rate limiting (429) and temporary server
  errors (500, 502, 503, 504), inside the existing 60-second total request budget.
- Retry-After is a minimum wait. Exponential backoff plus up to 250ms of jitter
  prevents a tight loop when the header is missing or zero. A large server delay
  is never shortened to fit the client budget; the client returns an explicit error.
- A shared in-process limiter serializes uncached requests for the same provider,
  resolved model and credential, with starts at least two seconds apart. It carries
  cooldowns between model instances and dashboard threads. Only an internal key
  digest identifies credentials in its registry; keys are absent from audit records.
- Successful and failed HTTP responses supply a strict allowlist of numeric quota
  headers. Zero remaining tokens waits for its token reset; zero remaining
  requests waits for its request reset. Groq's request header denotes daily
  requests, not requests per minute. Durations such as `2m59.56s` are parsed.
- Queueing, cooldown and transport share one wall deadline. Cooldown sleeps are
  interruptible 250ms pieces. A quota delay beyond the budget performs no early
  HTTP request. The audit marks those events `transport_attempted: false`.
- Cached replies bypass the request queue and incur no new provider call. Invalid
  scientific output, invalid citations and authentication errors are not retried
  to make a test pass. Existing no-paid-fallback and secret-redaction rules remain.

These controls apply within one AXIOM process. Groq applies organization-level
quotas, so other processes or API keys can still consume capacity. Daily quota
exhaustion may require waiting until the reset; an endless retry loop cannot add
quota. [Official Groq rate-limit and header documentation](https://console.groq.com/docs/rate-limits).

## Evidence and reproduction

The exact six-second 429 is tested with a fake clock: the second HTTP attempt
occurs six seconds later and succeeds. Additional tests cover repeated 429s,
temporary server outages, authentication failure, daily cooldowns, cache bypass,
concurrency, interrupted waits, malformed headers and total-deadline expiry.

The recovery batch is `runs/benchmarks/5951293d0f3949308ad989d3d687870c/` locally:
nine completed workflows, zero failed, seven cached provider replies and one
fresh successful review. This live rerun did not encounter another 429; the
automatic six-second recovery itself is demonstrated by the offline regression.
The original `dd75163e3e2d4727ad0012e4ad58d540` failure file was checked by hash
and remains unchanged. No scientific grades were created.

```powershell
$env:PYTHONPATH='src'
python -m axiom benchmark-report 5951293d0f3949308ad989d3d687870c
python -m axiom benchmark-run --provider groq --model qwen/qwen3.8-27b --systems baseline rag_only ignis --split dev --question-id Q001 --question-id Q004 --question-id Q008 --max-jobs 9
```

New manifests capture the retry policy and include `provider_limits.py` in code
hashes/snapshots. Existing historical batches stay readable; their old code hashes
correctly prevent resuming them under changed provider behavior. Each attempt
records its status, queue time, rate metadata and whether a retry was scheduled.
Scientific metrics still require independent annotations.
