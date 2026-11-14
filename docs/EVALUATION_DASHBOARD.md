# Evaluation dashboard · November 7, 2026

The Evaluation view visualizes the saved benchmark without making model requests.
Its numbers come from integrity-checked frozen jobs, not display constants or
model-generated scores. `GET /api/benchmark/RUN_ID/impact` computes the read-only
summary; Download results exports that same JSON.

## What the current run shows

Source run: `3c3cc0f1e4b949a8a33296e94417f13c`, generated November 6.

| Observed measure | Actual result |
| --- | ---: |
| Successful matched RAG/AXIOM pairs | 34 of 36 |
| Structured claims released by RAG on those pairs | 34 |
| Structured claims released after AXIOM checks | 21 |
| Additional claims withheld | 13 / 34, or 38.2% |
| Previously answered questions changed to withholding | 4 of 16 |
| Questions with any additional claim withheld | 10 |
| Completed executions across three systems | 106 of 108 |
| Failed executions, kept visible | 2 |
| Independent scientific grades | 0; accuracy remains unknown |

The primary comparison uses claims RAG actually released. The same paired raw
drafts contained 56 structured claims, including 22 in answers the writer had
already withheld. Those 22 are **not credited to the critic**. RAG and AXIOM share
the exact saved draft, evidence and linkage; failed/pending pairs are excluded.
Natural-language answer explanations can contain assertions outside the structured
claim list, so these are not exhaustive counts of every scientific assertion.

## Visuals and interaction

- **Before/after bars:** RAG output versus output after the safety critic, with the
  additional withholding area hatched. Counts and denominators are printed.
- **Reason bars:** citation, support/scope, applicability, missing conditions and
  numeric checks. Each bar filters the question list. A claim can have multiple
  flags; category totals must not be added to make an error count.
- **System outcomes:** answered, withheld, failed and pending on a common scale of
  scheduled questions. Full system totals are distinct from the 34-pair comparison.
- **Question matrix:** all cases and all three systems, with changed/failed filters.
  Opening a row compares RAG and AXIOM, highlights additional holds, exposes cited
  quotations and links into the existing full source/claim inspector. The baseline
  answer remains available in a disclosure. Writer withholding stays distinct.

| System · all 36 scheduled questions | Answered | Withheld | Failed |
| --- | ---: | ---: | ---: |
| Baseline LLM, no corpus | 4 | 32 | 0 |
| RAG, NASA passages | 18 | 18 | 0 |
| AXIOM, those drafts plus checks | 12 | 22 | 2 |

## What the numbers mean

The dashboard measures **recorded release decisions**, not scientific errors
prevented, hallucinations caught or an accuracy improvement. Model support labels
remain provisional. The critic includes deterministic checks and model review;
a rule-triggered hold is not a model identifying a scientifically wrong claim.

Some numeric flags involve identifiers such as DOIs or standard numbers. Other
holds can remove useful, properly bounded information. Independent review must
judge support and whether withholding was appropriate. The interface keeps this
boundary visible and leaves scientific quality unknown, rather than displaying
zero or an invented score. Cache/retry effects also prevent a fair latency or cost
comparison. The public benchmark test questions were visible during development.

## Verification

The full Python suite ran **443 tests: 438 passed, five Windows symlink checks
skipped**. All **31 dashboard script checks** passed, including fair denominators,
writer-abstained claims, failed/pending pairs, overlapping flags, immutable inputs,
filters, saved-case GET-only access, stale results and unavailable metrics.
Browser checks covered desktop light, 390px dark and 320px layouts without
horizontal overflow, reason filtering and the actual Q008 source comparison.
The original appearance and default viewport were restored.

The [validation snapshot](../benchmarks/evaluation_visualization_report.json)
records the derived numbers, test results and read-only checks. No new scientific
annotations, provider calls, dependency downloads or frozen benchmark changes
were required. A saved comparison with invalid hashes fails closed; the interface
shows unavailable charts instead of successful-looking zero results.

A fresh Python environment also installed the candidate offline from bundled
wheels. All three demos and nine local HTTP endpoints passed with model
construction blocked, including the new impact endpoint and its exact 34→21
claim accounting. The [offline release record](../benchmarks/evaluation_release_validation.json)
identifies the checked candidate; final packaging adds this record and paragraph
without changing runtime code or evidence.
