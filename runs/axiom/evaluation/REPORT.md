# AXIOM three-arm evaluation

Results commit: `da0612ba51e32640ce1cd5e6dbfe1ea8ea45bdc1`  
Run at: 2026-11-13T19:15:32.062117+00:00  
Recorded benchmark run: `3c3cc0f1e4b949a8a33296e94417f13c` (2026-11-06T19:25:38.725465+00:00)  
Dataset: 36 questions, 108 jobs, 106 completed, 2 execution failures.

**Provenance.** Question expectations are agent-drafted and unreviewed (`ai_draft_unreviewed`, no human reviewer). Monitor verdicts and metrics are automatic. Answer correctness is **not measured**.

## Arms

| Arm | Completed | Answered | Abstained | Expected-abstention agreement | Drafted claims | Retained claims | Dangling citations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 36 | 4 | 32 | 0.4444 | 9 | 8 | 1 |
| rag_only | 36 | 18 | 18 | 0.7222 | 60 | 38 | 0 |
| ignis | 34 | 12 | 22 | 0.7353 | 56 | 21 | 0 |

## Claim retention

| Arm | Drafted in answered runs | Drafted in abstained runs | Retained | Retention in answered runs | Drafted but not retained |
| --- | --- | --- | --- | --- | --- |
| baseline | 8 | 1 | 8 | 1.0000 | 1 |
| rag_only | 38 | 22 | 38 | 1.0000 | 22 |
| ignis | 27 | 29 | 21 | 0.7778 | 35 |

A drafted claim is not retained when the run abstains or when the critic does not clear it. Retention is a run-level decision, so a supported draft can be lost with an abstained answer.

## Question-level metrics

Intervals are 95% percentile intervals from 2,000 seeded question bootstrap resamples. Agreement is against unreviewed agent-drafted expectations.

| Arm | Answer coverage (95% CI) | Abstention rate (95% CI) | Draft-label agreement (95% CI) |
| --- | --- | --- | --- |
| baseline | 0.1111 (0.0278–0.2222; n=36) | 0.8889 (0.7778–0.9722; n=36) | 0.4444 (0.2778–0.6111; n=36) |
| rag_only | 0.5000 (0.3333–0.6667; n=36) | 0.5000 (0.3333–0.6667; n=36) | 0.7222 (0.5556–0.8611; n=36) |
| ignis | 0.3529 (0.2059–0.5000; n=34) | 0.6471 (0.5000–0.7941; n=34) | 0.7353 (0.5882–0.8824; n=34) |

Semantic evidence support, source correctness, unsupported quantitative claims, unsupported generalizations and applicability correctness are not measured because no independent claim-level annotations exist. Mechanical dangling-citation counts only check that citation IDs occur in retrieved evidence.

## Monitor outcomes

| Arm | Vacuous traces | Trace PASS/UNKNOWN/FAIL | Claim PASS/UNKNOWN/FAIL | Published verified/unverified | Unsafe verified publications |
| --- | --- | --- | --- | --- | --- |
| baseline | 32 | 32/3/1 | 0/6/2 | 0/8 | 0 |
| rag_only | 18 | 18/18/0 | 0/38/0 | 0/38 | 0 |
| ignis | 22 | 34/0/0 | 21/0/0 | 0/21 | 0 |

A vacuous trace has no claim in scope, so its PASS is not evidence that anything was verified. The two failed AXIOM executions are excluded from the completed denominators and are listed in the results JSON. A run-level property failure (P1, P7) applies to every claim in that run, which is why one dangling citation can fail more than one claim.

- AXIOM: 21 claims pass every process property, 0 carry a verified label and 21 passing claims stay explicitly unverified. A verified label additionally requires a `WITHIN_DOCUMENTED_SCOPE` assessment, which this run never made, so the monitor does not upgrade the label on its own.
- AXIOM requested an applicability assessment on 9 completed runs and answered 0 of them.
- RAG-only: 38 claims are UNKNOWN because there is no verification stage; the monitor cannot certify them, so they stay unverified rather than being called correct.
- Baseline: 2 claim verdicts FAIL and 1 citation(s) are dangling.

## Paired comparison

| Pair | Paired questions | Both answered | Both abstained | Only left answered | Only right answered |
| --- | --- | --- | --- | --- | --- |
| baseline__rag_only | 36 | 4 | 18 | 0 | 14 |
| rag_only__ignis | 34 | 12 | 18 | 4 | 0 |

Counts only. No significance test is reported.

- `rag_only` answered and `baseline` abstained: Q001 (answerable), Q002 (answerable), Q003 (answerable), Q007 (extrapolation), Q009 (citation_trap), Q011 (uncertainty), Q013 (answerable), Q014 (answerable), Q015 (answerable), Q017 (answerable), Q027 (extrapolation), Q030 (citation_trap), Q035 (uncertainty), Q036 (uncertainty).
- `rag_only` answered and `ignis` abstained: Q007 (extrapolation), Q008 (extrapolation), Q013 (answerable), Q014 (answerable).

## What the monitor did not verify

- The run is recorded, not fresh. A fresh three-arm run needs provider API keys that are not present in this environment.
- RAG-only and AXIOM share one saved draft; the comparison isolates verification and withholding, not the drafting model.
- Answer correctness and faithfulness are not measured: the rubrics are unreviewed agent drafts and no human reviewer scored the answers.
- Expected-action agreement uses unreviewed agent-drafted labels, so it is a behavioural check, not ground truth.
- Traces are post-hoc projections and do not record model-call failures. A failed execution with no claim is a vacuous PASS, so such runs are excluded from behavioural denominators and counted separately.
- No claim carries a verified label on this run: the pipeline made no documented-scope assessment, and the monitor does not upgrade a label on its own.
- 36 questions from one corpus of 12 documents are not a sample that supports a significance or generalisation claim.
- Bootstrap intervals are descriptive question-resampling intervals for answer coverage, abstention and agreement with unreviewed draft labels; they do not establish accuracy or a population effect.

## Provenance

- Question expectations: agent-drafted (manifest.inputs.questions (ai_draft_unreviewed))
- Human reviewer: None
- Metrics and monitor verdicts: automatic

