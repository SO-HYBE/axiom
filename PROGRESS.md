# AXIOM progress

Living record for the AXIOM evolution of axiom. Scope, decisions and blockers are
kept here; measurements live in `runs/axiom/` only after a real run exists.

## Phase plan (stated before coding)

Will complete: 0 audit, 1 applicability engine, 2 trace + three-valued monitor,
3 mutation lab with integrity ablation, 4 extraction validation, 5 offline
three-arm analysis, 6 UI, and 7 docs. A fresh live three-arm run requires
provider keys that are not present in this environment; that is documented as a
blocker rather than simulated.

Cut: optional timing extension, interview-preparation guide, dataset growth
beyond the recorded 36 questions, and UI polish beyond the required presets and
heatmap.

## Done

### Phase 0 — audit

- Branch `axiom` created from the released tree.
- Baseline suite before repair: 516 tests, 1 failure, 5 skips. The failure was
  `test_required_release_files_are_present` because a later `init` commit had
  deleted `PROJECT_WORK.md`. The file was restored unaltered from `c6f44f7`
  (commit `ef75d0f`) because the work contract and the release test require it.
- Corpus and pipeline inspected: 12 NASA documents, 294 passages, 5 investigation
  groups, deterministic critic, scenario assessment, benchmark runner and the
  frozen 36-question run.

### Phase 1 — deterministic applicability engine

- `src/axiom/applicability.py`: nine logical fields mapped onto documented
  attributes (material→fuel, configuration→apparatus), per-field
  MATCH/MISMATCH/CONFLICTING/UNKNOWN, overall outcome with a fixed precedence,
  field evidence with quote/locator/validation status, limitations.
- Overall precedence, evaluated in this order and reported with every result:
  1. `CONFLICTING_EVIDENCE` — contradictory documented values for a specified field.
  2. `WITHIN_DOCUMENTED_SCOPE` — one direct investigation covers every specified
     field (necessary, never sufficient for physical transferability).
  3. `CONDITION_MISMATCH` — documented values contradict the scenario and nothing matches.
  4. `INSUFFICIENT_INFORMATION` — missing/unqualified field or no single covering investigation.
- `temperature_k` added with affine conversion (K, °C, °F) and bounds rejection.
  A conservative extractor accepts an imposed test/chamber/preheat temperature and
  rejects flame, exhaust, wall, outlet, limit and instrument-difference readings.
  The shipped corpus yields one eligible temperature record (297.25 K, SAFFIRE V)
  and no invented values elsewhere.
- `scenario.assess` returns `applicability_engine`; the Mission Scenario view has a
  "Documented-scope verdict" section with text labels (not colour alone) and a
  temperature input.
- Tests: `tests/test_applicability_engine.py` (22 tests) covers exact, ranges and
  inclusive boundaries, mismatch, missing, ambiguous, conflicting, precedence,
  contextual evidence, unit conversion, invalid values, extraction exclusions and
  the scenario integration.
- Suite after Phase 1: 538 tests, 0 failures, 5 skips; Node 31/31.

### Phase 2 — versioned traces and a three-valued monitor

- `src/axiom/trace.py`: `axiom-trace-v1` events with ten types, authoritative
  sequence numbers, an optional timestamp carried as data only, and a SHA-256
  content hash over canonical event fields. `build_trace` projects a recorded run
  into a trace without inventing events; the baseline and RAG-only arms have no
  verification stage and are published with an explicit `unverified` label.
- `integrity()` classifies trust before any property runs: contiguous sequence,
  manifest count and last sequence, delivery order, hash mismatch, malformed
  events, identical duplicates (idempotent, discarded, noted) and conflicting
  duplicates (event untrusted). Nothing is repaired or reconstructed.
- `src/axiom/monitor.py`: properties P1–P8 in a versioned registry, each with its
  definition, pass/fail/unknown condition and required event types. PASS requires
  present, trusted observations and a complete run; absence is FAIL only in a
  complete run and UNKNOWN otherwise; aggregate is FAIL > UNKNOWN > PASS.
- Fixed output policy: PASS → published as verified, UNKNOWN → published with an
  explicit unverified label, FAIL → withheld.
- P2 requires an applicability check only when the recorded verification declares
  `APPLICABILITY_CHECKED` in `required_checks` (set by `build_trace` when
  applicability was requested or assessed); metadata validation is always required.
- Reference verdicts on the 108 recorded traces: 86 PASS, 21 UNKNOWN, 1 FAIL
  (Q026 baseline, a dangling citation with no retrieval). The 21 UNKNOWN are
  RAG-only claims with no verification (P3).
- Tests: `tests/test_trace_monitor.py` (35 tests) covers the schema, hash,
  integrity flags, P1–P8, the aggregate, the policy, and projection of real and
  baseline traces.
- Suite after Phase 2: 573 tests, 0 failures, 5 skips; Node 31/31.

### Phase 3 — trace-mutation lab and seeded faults

- `src/axiom/mutations.py`: eight channel operators (loss, reorder,
  duplicate_identical, corrupt_payload, corrupt_evidence_ref, corrupt_seq,
  corrupt_timestamp, delay) that never recompute a hash, plus three labelled
  adversarial operators (duplicate_conflicting, corrupt_evidence_ref_rehash,
  corrupt_seq_rehash). The input trace is never modified and the same seed
  reproduces the same mutation.
- `src/axiom/faults.py`: ten seeded pipeline faults whose labels are fixed by
  construction (declared expected property and verdict), including two P2 faults
  and three P5 faults so that every property except P6 has an injected fault.
- `src/axiom/mutation_lab.py` writes `runs/axiom/trace_lab/results.json` with
  commit, timestamp, dataset size, definitions, an integrity-layer ablation and a
  property × operator matrix. Undefined rates are `null`, never zero.
- Measured at commit `9c0f933`, 2026-11-13T18:31:15Z, 108 traces (36 questions ×
  3 systems), 12 918 channel cases, seeds 0–1:
  - integrity ON: 10 676 correct conclusive, 0 false conclusive, 2 242 unknown
    (coverage 0.8264, trustworthy conclusive 1.0, false conclusive 0.0).
  - integrity OFF: 12 774 correct, 68 false, 76 unknown (coverage 0.9941,
    trustworthy conclusive 0.9947, false conclusive 0.0053).
  - The off arm is more conclusive and less sound. The result is a
    soundness/coverage trade-off, not an accuracy win for either arm.
  - Seeded-fault detection 1.0 for all ten faults; applicability counts 12–108 per
    fault. `dangling_citation` also fails P6 in all 34 applicable cases (collateral,
    expected: a dangling citation is both a provenance and a citation violation).
- Tests: `tests/test_mutations.py` (26 tests) covers determinism, immutability,
  each operator's mechanics, stale hashes, adversarial rehashing, composition,
  every seeded fault, fault skipping, and the metric arithmetic including
  null-not-zero denominators.
- Suite after Phase 3: 599 tests, 0 failures, 5 skips; Node 31/31.

### Phase 4 — extraction validation

- `src/axiom/extraction_validation.py`: a deterministic sample chosen by unit
  tokens only (`temperature` all, `pressure` every 2nd, `flow` every 5th,
  `oxygen` every 8th, plus exclusion controls), a scoring harness whose
  tolerances and matching rules are fixed in the module before any label is
  drafted, and a CLI that writes `runs/axiom/extraction_validation/results.json`.
- The sample file carries passage text only. It has no `conditions` field, so a
  label cannot be copied from the extractor.
- 33 sampled chunks, 28 labeled, **57 labels** (39 eligible, 18 not eligible),
  11 sources, 6 experiment groups. Every label carries an exact quote and
  locator; a label whose quote is absent from the passage is rejected by the
  harness instead of being scored.
- Measured at commit `5eb61c8`, 2026-11-13T18:38:06Z:
  - overall precision 0.8182, recall 0.6923, F1 0.75;
  - `oxygen_percent` 0.9 / 0.6, `pressure_kpa` 1.0 / 0.8,
    `flow_cm_s` 0.6429 / 0.8182, `temperature_k` 1.0 / 0.3333;
  - numeric agreement 1.0, maximum absolute error 0.0 on matched values;
  - 4 exclusion violations, all `flow_cm_s` limits (quenching or blow-off
    boundaries) recorded as eligible conditions; 6 false positives, 12 misses.
- Disclosed scoring change: the first pass matched every table row one-to-one
  and reported precision 0.54. Repeated identical values are now deduplicated on
  both sides and one legitimately stated 21% O2 test case was labeled. No
  extractor code was changed in response to the labels, so the reported numbers
  remain an out-of-sample estimate for the shipped extractor.
- The misses are concrete and reported, not hidden: "O2 20%" value-after-label
  phrasing, `13% < O2 < 30%` inequality notation, dash-prefixed pressures
  (`Air -1 atm`), temperatures stated as "initial conditions (24°C)" without the
  word "temperature", and oxygen levels inside blow-off-limit sentences that the
  extractor classifies as limits.
- Tests: `tests/test_extraction_validation.py` (11 tests) covers quote
  rejection, matching, tolerance boundaries, deduplication, null rates,
  exclusion handling, and sample determinism/text-only content.
- Suite after Phase 4: 610 tests, 0 failures, 5 skips; Node 31/31.
- `runs/axiom/extraction_validation/REVIEW.md` is the reviewer sheet: measured
  table, every disagreement listed, and a sign-off block whose reviewer and date
  are `null`. `sample_review.txt` is the passage-only view used for drafting.
  No human review has happened; the labels are not presented as validated.

### Phase 5 — recorded three-arm evaluation

- `src/axiom/axiom_evaluation.py` analyzes the frozen 36-question benchmark run
  (`3c3cc0f1e4b949a8a33296e94417f13c`) offline. It reports scheduled/completed/
  failed jobs, answer and abstention behavior, retained claims, mechanical
  citation resolution, monitor verdicts and paired outcomes.
- 108 jobs were scheduled, 106 completed and two failed. The baseline arm
  completed 36, RAG completed 36 and axiom completed 34. RAG and axiom share the
  same saved draft, so the comparison isolates checking/withholding.
- Added seeded 2,000-resample 95% question bootstrap intervals for answer
  coverage, abstention rate and agreement with draft labels. These are
  descriptive only. Semantic evidence support, citation-to-source correctness,
  unsupported claim rates, applicability correctness, answer correctness and
  faithfulness remain null: no independent answer grades exist.
- The saved shuffled answer packet already has a separate private mapping and
  zero grades. No unblinding or scientific score was created. A fresh run was
  not attempted because provider credentials are absent.
- Output: `runs/axiom/evaluation/results.json` and `REPORT.md`. Provenance and
  run commit, timestamp and sample size are included.
- Tests: evaluation unit tests cover rate denominators, failure handling,
  monitor policies, deterministic bootstrap intervals and report generation.

### Phase 6 — AXIOM dashboard

- Added the AXIOM results panel inside Evaluation while preserving Research,
  Mission Scenario, Saved demos and Source Library views. It reads only the
  evaluation, mutation and extraction result files; missing files display “not
  run.”
- Added a saved-case inspector, side-by-side original/mutated traces for the
  three requested presets, per-property verdict comparison and integrity ON/OFF
  mutation heatmap. Mutation demos use a saved benchmark trace and do not alter
  stored results.
- Added fixed read-only result endpoints and an allowlisted, bounded POST demo
  endpoint. Result file parse failures fail closed.

### Phase 7 — current AXIOM docs and report

- Added `docs/FORMAL_PROPERTIES.md`, `TRACE_MUTATIONS.md`,
  `METADATA_VALIDATION.md`, `EVALUATION.md`, `RESEARCH_MOTIVATION.md`, and
  `AXIOM_FINAL_REPORT.md`; updated README, architecture and documentation index.
- The report lists exact review artifacts and distinguishes agent-drafted,
  automatic and absent human-reviewed labels. Optional learning and interview
  guides were cut under the supplied cut list.

## NASA Space Apps official resource ingestion follow-on — November 13, 2026

- Acquired original NASA/YouTube source pages for R2–R10; the R4 NASA guide
  PDF is also acquired and text-indexed with page locators. The NASA PSI database
  guide PDF is retained in the local external source cache; its provenance and
  SHA-256 remain in the project. PDF binaries are outside the repository because
  `tests/test_shipped_corpus.py` explicitly forbids PDFs inside the project.
- R2–R10 original page assets carry provenance sidecars. Indexed passage count
  for R2 and R4–R10 is 131; R4 contributes 64 page/article chunks total.
  R8–R10 remain marked `review_required` for rights and excluded from retrieval.
- R3 watch page is retained, but the advertised English timed-text endpoint
  returned an empty response. No transcript or caption text was fabricated;
  R3 is acquired but not indexed.
- Live resource report: 10/10 resource identities have acquired bytes or mapped
  PSI catalog chunks; 9/10 have indexed chunks; 143 indexed chunks total; zero
  raw experimental PSI files and zero extracted experiment records. R1 still
  consists of pre-existing catalog records/listing plus the new database guide.
  No source metadata has human-reviewed status.
- Corrected the resource report and coverage docs to distinguish acquisition,
  indexing, catalog material, review-required sources and raw datasets.
- Regression: `python -m unittest discover -s tests -v` — 645 passed, 0 failed,
  5 skipped. An earlier run caught the no-PDF-in-repository rule; source PDFs
  were preserved in the external local cache and the suite passed afterward.
- Remaining: PSI search-result resolution and individual dataset file access,
  rights checks and data parsing; obtaining a usable official R3 caption track;
  rights review for R8–R10. These were not simulated or claimed as complete.

## Extraction-label human review — November 13, 2026

- Applied the project owner's 18 decisions in `runs/axiom/extraction_validation/review_decisions.jsonl`; the original agent-drafted `labels.jsonl` remains unchanged. This is partial human review by one reviewer, not independent annotation.
- Applied the 40 cm/s eligible decision and corrected the reviewed report text for `O2 21%`. Reviewed missed values and rejected extra predictions are retained in the audit log.
- Recomputed `results.json`: precision 0.8485, recall 0.7000, F1 0.7671; 40 eligible and 17 not-eligible labels; 5 false positives, 12 false negatives. These are descriptive for the fixed sample, not population estimates.
- `tests.test_extraction_validation`: 11 passed. Full suite in the current restricted network sandbox: 645 tests, 52 errors from loopback/network-dependent tests, 5 skipped. The same suite had passed before this session's sandbox restriction.

## In progress

- None. User review and provider-dependent follow-up remain pending below.

## Blocked

- Public deployment: no hosting credentials or domain in this environment. The
  application is served locally only; no deployment is claimed.
- Live three-arm model run: no provider API keys. The analysis runs offline over
  the recorded benchmark responses; the missing live run is logged as a
  limitation.

### Final verification — November 13, 2026

- Python: `python -m unittest discover -s tests -v` — 636 passed, 0 failed,
  5 skipped (Windows symlink privilege). Initial sandbox run could not bind
  loopback sockets; the same suite passed with reviewed socket access.
- Dashboard JavaScript: `node tests/js/dashboard_models.cjs` — 31 passed,
  0 failed. New AXIOM initialization was made tolerant of the limited DOM test
  harness while preserving browser behavior.
- No model calls, paid API calls or model downloads were made.
- Visual browser inspection remains unverified: the in-app browser could not
  connect to the local server (`ERR_CONNECTION_TIMED_OUT`).

## Decisions

1. Keep the Python package name `axiom`; brand the product AXIOM in UI and docs.
2. Reuse documented attributes instead of duplicating fields: material→`fuel`,
   configuration→`apparatus`, temperature→new `temperature_k`.
3. Conflicting documentation outranks a scope claim: a scope claim requires both
   full coverage of the specified fields and no conflicting field.
4. Missing source information is never an extraction error and never a zero.
5. The mutator never recomputes content hashes; adversarial hash recomputation is
   reported separately and never mixed into the channel-damage metrics.
6. Labels and ground truth carry `human-reviewed | agent-drafted | automatic`
   provenance. The assistant is not the human reviewer.
7. A monitor verdict never comes from a language model. P2's applicability
   requirement follows the recorded verification rather than being assumed, so a
   run that never requested an applicability check is not failed for lacking one.
8. Integrity ON is expected to abstain more often than OFF: damage becomes
   UNKNOWN instead of a confident wrong verdict. Comparisons must report
   soundness and coverage together.
