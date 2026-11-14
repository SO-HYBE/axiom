# Validation record · October 31, 2026

- 45 unittest checks passed after integration: ingestion bounds/redirect policy, repeated hashes, retrieval, citation forgery, scientific unit case, unknown conditions, model failure, independent evaluation denominators and local HTTP flow.
- Three NASA PDFs produced 66 chunks from 61 physical pages. Repeat ingestion retained corpus hash `aaf8fabc45b7740bc12d933dade040cb2665209411e16b5f74944baac2dc669b`.
- A real local `llama3.2:latest` AXIOM smoke call returned an explicit abstention. This confirms connectivity and structured parsing, not scientific quality or superiority. Its audit record is in the local runs directory and predates the final output-contract adjustment.
- No paid model calls or model downloads were performed.
- No 36-question model comparison or human grading has been completed.
- Browser verification of official pages was unavailable; browser automation stopped because it could not establish the current browser URL. Central detailed rules/resources remain unresolved.
- The local dashboard passed HTTP integration checks, but visual browser QA is pending.

Known implementation limits: paraphrases remain withheld, condition metadata is null, lexical retrieval can miss paraphrased questions, same-model semantic checks are provisional, failed model envelopes are not fully retained for audit yet. These are open later-phase tasks, not hidden benchmark successes.

## Phase 1 integration · November 2, 2026

69 automated tests passed. The 47 condition records pass both the runtime validator and Draft 2020-12 schema. They remain AI drafts: 36 reported, 9 proposed, 2 background. 40 unique passages are queued for human review; none is marked reviewed.

Read-only corpus audit confirmed 12 PDFs / 215 physical pages / 294 chunks and zero ingestion failures. All 12 original PDF hashes, 12 metadata hashes and corpus/inventory hashes match the manifest. New corpus hash: b47916f2bd8cd6a35f0253cc8473c3cfd5042b59c9e922e6b49d481de0e27c9a.

The dashboard condition endpoint and empty-state behavior pass HTTP tests. Visual browser QA and scientific review remain pending. No raw PSI measurements were downloaded. Technical Phase 1 work is delivered; the scientific acceptance gate stays open.

## Phase 2 development · November 2

Participant textual-support feedback on five sampled passages is recorded with original responses and separate assistant observations. The engineering audit reports five participant cases independently from scientific-review counts. Source filters, explicit overview inclusion, ranking explanations, exact duplicate attribution and a development-tuned relevance guard are integrated into CLI, research and dashboard paths.

98 tests passed after integration. On 12 frozen development queries, default retrieval hit 9/10 answerable questions, retrieved 9/12 mapped spans and returned no results for 1/2 unrelated questions. With overviews explicitly included, results were 10/10, 10/12 and 1/2 respectively. The overview-inclusive span result meets the 80% development target. Default mapped-span recall and unrelated-query detection remain open. See history/PHASE2_STATUS.md and the ranked reports for limitations and tuning disclosure.

## Phase 3 and initial critic work · November 3

126 automated tests passed after integrating provisional summaries, call/context limits, run records, numeric association checks and provider caching/deadlines. The actual dashboard HTTP endpoint replayed three cached model responses for the SIBAL question, returned a provisional summary and saved the run locally.

Fresh Groq smoke runs answered the SIBAL composition question and withheld the unsupported universal fireproof-certification answer. A valid-citation injected reversal of the composition was blocked by the numeric-association guard. An unrelated exoplanet question retrieved no evidence and made no model call. Full model-answer benchmark scores remain pending. Phase 2's unresolved default recall and unrelated-query issue remain documented.

## Phase 4 evidence review · November 4

162 tests passed. Model reviews now inspect all selected retrieved passages and require structured verdicts, reasons, uncertainty and exact evidence spans. Supported assertions carrying limitations or counterevidence become uncertain. Exact source quotations in model mode also undergo context review. Hosted grouped reviews preserve per-claim decisions and validate provenance before cache storage and replay.

A live grouped Groq run returned two supported provisional SIBAL claims using one review request (2,985 new tokens) and a cached draft. The first individual-review attempt had reached a rate limit and remains retained in local run records. The normal dashboard endpoint then replayed both model responses from cache, returned four evidence checks and saved the result locally. FLEX scope-hint inspection preserved two proposed range differences. Full scientific model accuracy and broader benchmark comparison remain pending.

A pre-existing review-history race under coarse clocks was corrected using sequence numbers allocated under an OS file lock. Equal-timestamp and simultaneous-write tests verify that later revisions take precedence. No participant responses were changed.

## Phase 5 dashboard · November 4

196 Python tests ran: 195 passed and one Windows symlink test was skipped because
symlink creation is unavailable. The Node dashboard runner passed all 10 checks.
New coverage includes same-model comparison controls, target input parity,
frozen corpus inputs, per-side execution/storage failures, bounded history,
pagination, invalid hosts/paths, old runs and GET-only reopening.

Actual browser verification covered the SIBAL comparison, saved-pair reopening,
claim inspection, page-linked sources, extractive offline behavior, insufficient
evidence and missing applicability conditions. A 390-pixel viewport displayed
stacked cards without horizontal overflow. One fresh Groq baseline response and
two cached AXIOM responses were preserved in the paired local record documented
in history/PHASE5_STATUS.md. This is a functional example, not a benchmark score or a
latency comparison. Earlier visual-QA pending notes describe historical phases.

## Phase 6 evaluation machinery · November 5

247 tests ran: 245 passed and two Windows symlink-creation tests were skipped.
All 12 Node dashboard tests passed. Source-scope audit and verified cached
abstracts authorize 10 of the 36 unreviewed question scopes. The offline run
completed those 10, failed none and retained 26 as pending source work.

The bounded Groq pilot scheduled three development questions across baseline,
RAG-only and AXIOM: eight completed, one review rate-limit failure, no grades.
Resuming preserved the failed record and made no model requests. The report does
not convert failures or unavailable sources into correct abstentions. Quality
scores remain null without independent labels. Browser checks covered actual
counts, missing scores, saved answers, source links and a 390-pixel layout.

Frozen hashes/snapshots, nested record corruption, changed-model/code refusal,
job ordering, shared RAG drafts, successful retries, review failures and shuffled
packets have deterministic regression coverage. See history/PHASE6_STATUS.md for local
run IDs, commands and limitations. The scientific Phase 6 gate remains open.

## Provider cooldown recovery · November 5

263 tests ran: 261 passed and two Windows symlink cases skipped. Provider tests
reproduce the actual six-second cooldown with a fake clock and verify no early
retry, bounded repeated failures, service-error backoff, quota resets, credential
redaction, cache bypass and shared request serialization.

The new three-question recovery pilot completed nine workflows, failed none,
reused seven cached replies and made one fresh successful review request. The
original failed review's file hash is unchanged. No live 429 occurred during this
rerun; simulated tests establish retry timing. See PROVIDER_RELIABILITY.md for the
saved run and current policy. All scientific scores remain ungraded.

## Phase 5.1 interface refinement · November 5

The full suite remains green: 263 checks ran, 261 passed and two Windows symlink
tests skipped. The dashboard's Node runner now passes 22 behavior checks. New
coverage protects navigation, mobile inert/focus state, appearance controls,
keyboard submission, cleared/restored question input and stale-response ordering.

Actual browser checks covered light/dark layouts, the two provider-specific
Nemotron choices, saved answers and comparisons, evaluation counts, source cards,
a real no-model question and its original PDF page link. Both 390px and 320px
layouts fit without horizontal overflow. Source provenance, scientific labels
and existing backend behavior are unchanged. See history/FRONTEND_REFINEMENT.md.

## Phase 6B named-source acquisition · November 6

The full offline suite ran 295 tests: 293 passed and two Windows symlink tests
skipped. All 22 shipped-dashboard JavaScript checks passed. New regressions cover
exact PSI accession/version/DOI/license, source-description opt-in, heading scope,
catalog file-list provenance, corrupt/forged raw and derived caches, path and size
bounds, offline replay and changed-input resume refusal. A fresh local HTTP check
returned 35 available question scopes and nine saved pilot answers.

Actual acquisition admitted seven exact NASA references and 18 located passages;
the combined benchmark has 314 passages while the core PDF corpus stays at 294.
The audit found 35/36 source scopes available, 24 cases with candidates and eleven
without a lexical match. Q026's original blog redirects to an unrelated archive
and remains pending. No alternative source was silently substituted.

Offline run `df045f2105624c3b99a92475eb9fc9fb` completed 35 extractive jobs with
zero failures and Q026 pending. Groq pilot `a96001f691e547fe93a3f03a54a86603`
completed Q002/Q003/Q009 across three systems: nine workflows, zero failures.
Nine successful fresh calls and three recovered rate-limited attempts were
recorded. RAG and AXIOM share the saved drafting result. No scientific grades
were supplied; execution success does not establish answer quality. See
history/PHASE6B_STATUS.md for source rights, original URLs and remaining gates.

## Phase 6C full comparison and recovery · November 6

The full suite ran 319 tests: 317 passed, two Windows symlink checks skipped.
Fourteen inspector regressions cover snapshot/record corruption, scope and model
identity, shared drafts, prediction fidelity, pending cases and policy counts.
Ten transport regressions cover safe classification, transient retry, terminal
errors, deadlines, response size and credential-safe audit records.

Initial run `8b005bbca07849db97b403545b13de8b` accounted for all 108 jobs:
100 completed, five failed, three Q026 source-blocked. Recovery
`233c7b8afd134eac937062d6b4144893` recorded 103 completed, two invalid critic
responses and three Q026 jobs pending. Both actual runs pass offline integrity
inspection. All five initial failed job files retain their saved hashes.
Recovery includes 75 cache hits, three fresh successes, two invalid responses
and a confirmed socket-timeout attempt recovered with bounded retry.

The review packet has 103 shuffled successful executions, all grades null. Its
ZIP excludes the private mapping and credentials and includes the frozen corpus,
source inventories and reviewer guide. Exact packet/bundle hashes and both
passes' observations are in benchmarks/phase6c_engineering_report.json. Scientific
accuracy, appropriate abstention and safety improvement remain ungraded.

## Phase 7 release and clean environment · November 6

The complete suite ran 345 tests:342 passed and three Windows symlink checks
skipped. All24 shipped-dashboard checks passed. A candidate release verified
its allowlisted file hashes and installed into a new virtual environment using
only bundled dependency wheels with --no-index and no API keys. Its294 core
passages, three demos,35 named source scopes and saved benchmark integrity
loaded correctly. Status/demo/evaluation HTTP checks ran with model construction
disabled and recorded zero constructions. The actual Windows launcher created
its own environment and served all three demos. Browser QA opened the cited
answer and source, withheld applicability case and retrieval-gap case.

API keys, model caches, private reviewer mapping and virtual environments are
excluded from packaging. Dates, rights, source bytes and frozen failures remain
intact. See history/PHASE7_STATUS.md, RELEASE_GUIDE.md and benchmarks/phase7_validation.json.

## Submission migration and clean repository - November 11, 2026

The allowlisted release repository was assembled as a fresh directory with its
own history. No file was backdated and the original workspace was left intact.
Corpus, inventory, benchmark run, demonstrations and documentation counts were
re-verified against the shipped files rather than copied from earlier reports.

The full offline suite in a new virtual environment installed from the bundled
wheelhouse ran **516 tests: 511 passed and 5 skipped**. All five skips are
Windows symlink-privilege cases (`OS does not permit symlinks for this test
process` / `Symlink creation unavailable on this host`):

- `test_benchmark_scope.BenchmarkScopeTests.test_cache_symlink_outside_root_rejected`
- `test_provider_diagnostics.ProviderDiagnosticTests.test_existing_non_directory_or_redirected_capture_root_is_refused`
- `test_release.ReleaseTests.test_symlinked_allowlisted_source_is_rejected`
- `test_review_bundle.ReviewBundleTests.test_redirected_output_is_not_followed`
- `test_run_records.RunRecordTests.test_symlink_records_and_redirected_directory_rejected`

The Node dashboard suite ran **31 tests, 31 passed, 0 failed**. Two new test
modules cover the migration itself: `tests/test_shipped_corpus.py` (shipped
corpus counts, rights metadata, four classifications, citation integrity,
proposal traceability, unit conversion, persistence and release hygiene) and
`tests/test_http_service.py` (health probe, declared and undeclared hosts,
security headers).

Docker 28.3.2 built image `axiom:1.0.0`, and Compose reached `healthy` on
`/healthz`. A saved scenario survived `docker compose restart` and a full
`down` / `up -d` cycle in the `axiom-scenarios` named volume. An undeclared
`Host` header received `403`; a host declared through `AXIOM_ALLOWED_HOSTS`
received `200`.

A responsive layout defect was found during screenshot capture: at 390 px the
Mission Scenario grid column was widened by the 760 px comparison table, which
pushed the scenario builder past the viewport. The fix constrains grid children
with `min-width:0` and contains the table in a horizontally scrollable wrapper.
Document-level `scrollWidth` now equals the 390 px viewport, and is 885 px at a
900 px viewport (scrollbar gutter only). Screenshots in `docs/screenshots/` were
re-captured after the fix.

No public deployment was performed and none is claimed.

## AXIOM completion checkpoint — November 13, 2026

The AXIOM branch ran the repository-required command
`python -m unittest discover -s tests -v`: **636 tests, 636 passed, 0 failed,
5 skipped**. The five skips are the existing Windows symlink-permission cases
listed above. The command first ran in the default sandbox, where loopback
socket binding was denied and HTTP integration cases errored with WinError
10013. It was rerun with reviewed local socket access; the complete suite then
passed. The dashboard JavaScript suite ran **31 tests, 31 passed, 0 failed**.

AXIOM-specific suites include 16 evaluation tests, four trace-demo tests, four
allowlisted result-loader tests, plus the existing applicability, trace-monitor,
mutation and extraction-validation coverage. No model or paid API calls were
made. The browser visual pass could not reach the local server from the isolated
in-app browser (`ERR_CONNECTION_TIMED_OUT`); the UI was checked by the dashboard
script suite and the API result loader/trace-demo tests instead.

## Static frontend split and Render preparation — November 14, 2026

The dashboard was separated from its API origin so the page can be hosted on a
static site. The page now reads `window.AXIOM_API_BASE` from `config.js`; the
Python service serves that file with an empty value, keeping local and container
use same-origin. The API gained an exact-origin allow-list
(`AXIOM_ALLOWED_ORIGINS` / `--allowed-origin`), `OPTIONS` preflight handling for
the five JSON `POST` paths, and origin-aware `connect-src` in its
Content-Security-Policy. No wildcard CORS rule exists.

`node scripts/render_static_config.mjs` copies the page to `dist/index.html` and
writes `dist/config.js` from `API_BASE_URL`. It refuses a Render build without
that variable and rejects values that are not bare HTTP(S) origins. `render.yaml`
declares one free static site and one free Python web service.

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` | 652 tests, 652 passed, 0 failed, 5 skipped |
| `node --test tests/js/dashboard_models.cjs` | 32 tests, 32 passed, 0 failed |
| Split-origin browser run (static `127.0.0.1:5500`, API `127.0.0.1:8767`) | Dashboard loaded; `/api/status` returned `200` through CORS; 294 chunks and 12 ingested sources |
| Cross-origin `POST /api/axiom/trace-demo` after `OPTIONS` | `200`; preflight returned `204` |
| Browser console during the split-origin run | No CORS or Content-Security-Policy errors |
| Same-origin `GET /config.js` from the Python service | `200` with `window.AXIOM_API_BASE = ""` |
| Docker image rebuilt after the change | `axiom:1.0.0` built; container reached `healthy` |
| Container `GET /healthz`, `GET /config.js`, `GET /` | `200`, `200`, `200` |
| Container: undeclared origin | `200` with no `Access-Control-Allow-Origin` |
| Container: origin declared through `AXIOM_ALLOWED_ORIGINS` | CORS header echoed; preflight `204` |
| Container browser run | Dashboard showed 294 chunks and 12 documents with no console errors |
| Render deployment | **Not performed** |
| Porkbun DNS records | **Not created or changed** |

The five skips are the same Windows symlink-permission cases listed in the
November 11 entry. No model, paid API or network source call was made. The
in-app browser could reach loopback for this run, so the earlier workaround of
testing only through the script suite did not apply. `render.yaml` has not been
synced to a Render account; `docs/RENDER_DEPLOYMENT.md` records the exact
commands, free-tier limits and DNS records for a later deployment.
