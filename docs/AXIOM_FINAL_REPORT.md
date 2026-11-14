# AXIOM implementation report

## Delivered

- Deterministic applicability comparisons over the nine requested condition
  fields, with explicit MATCH/MISMATCH/UNKNOWN/conflict evidence and documented
  outcome precedence.
- Versioned execution traces, a three-valued P1–P8 monitor, observation
  integrity layer, and fixed publication policy.
- Seeded channel mutations, seeded-fault traces, integrity ON/OFF ablation,
  per-property/operator metrics, and an in-memory UI demo path.
- Source-quoted extraction review set and a fixed-sample scoring report.
- Offline analysis of the recorded three-arm run, including question-level
  bootstrap intervals. A fresh model run is blocked by missing provider keys;
  it was not simulated.
- AXIOM Assurance Inspector, Trace Lab, mutation heatmap, extraction panel and
  file-backed results endpoints. Existing research, scenario, planner, critic,
  persistence and APIs remain in place.

The phase-by-phase implementation and measured values are recorded in
[`PROGRESS.md`](../PROGRESS.md), [`TRACE_MUTATIONS.md`](TRACE_MUTATIONS.md),
[`METADATA_VALIDATION.md`](METADATA_VALIDATION.md), and
[`EVALUATION.md`](EVALUATION.md). The panel shows “not run” if a results file is
missing and reports commit, timestamp and dataset size for saved results.

## Results and limits

The extraction sample has 33 chunks, 28 labeled chunks, 57 agent-drafted field
labels, 11 sources and six investigation groups. Overall precision/recall/F1 is
0.8182/0.6923/0.75 on this fixed sample. No human scientific validation has
occurred and no independent holdout or second annotator is claimed.

The recorded three-arm run has 36 questions and 108 scheduled jobs: 106
completed and two failed. Baseline answered 4/36, RAG 18/36 and AXIOM 12/34
completed. These are response/abstention outcomes, not correctness scores.
Semantic evidence support, source correctness, unsupported claim rates,
applicability correctness, answer correctness and faithfulness are null because
there are no independent claim-level grades. The question expectations are
agent-drafted and unreviewed. There is no finding that AXIOM improves scientific
answer quality.

The mutation measurement used 108 traces and 12,918 channel cases. Integrity ON
produced 10,676 correct conclusive, 0 false conclusive and 2,242 UNKNOWN. Integrity
OFF produced 12,774 correct, 68 false-conclusive and 76 UNKNOWN. The results show
a coverage/trust trade-off on this generated sample; they do not imply immunity
to arbitrary mutation. The 2026 source commit and run time are in the JSON
measurement record.

## Startup and two-minute walkthrough

Run `python -m axiom serve --port 8765` from the repository root and open
`http://127.0.0.1:8765`. In Research, ask a question grounded in a NASA passage;
open Mission scenario and load the crew-cabin preset; inspect the documented
scope outcome and claim evidence; open Evaluation → AXIOM Assurance; choose one
of the three trace presets and compare per-property verdicts and the aggregate
mutation heatmap. The evaluations are saved offline results and the trace demo
is a deterministic replay over one saved run.

Suggested closing line: “AXIOM doesn't just ask whether an AI answer has a
citation. It checks whether the documented experimental conditions cover the
claim — and whether the assurance system can trust the observations behind its
own verdict.”

## Five concepts to understand

1. Applicability is a necessary check against documented experiment conditions,
   not proof that evidence transfers physically to a spacecraft scenario.
2. PASS/FAIL/UNKNOWN describe process observations; only trusted observed
   violations justify FAIL, and PASS requires a complete finite run.
3. Event hashes catch accidental corruption, not malicious edits by an actor
   who can recompute the hash.
4. Mutation immunity is conditional on the tested mutation and trace corpus;
   report conclusive trust together with coverage and abstention.
5. Citation-ID resolution and process monitoring cannot establish that the
   source semantically entails a claim; that needs independent source review.

## Questions for Dr. Sean Kauffman

1. Which parts of the unreliable-channel model are most important to preserve
   when the events are post-hoc projections rather than an online monitor's
   direct input?
2. Is the integrity-ON/OFF comparison here a useful application-level
   operationalization of trustworthy verdicts, and what failure modes would
   make the reference verdict unreliable?
3. How would you recommend separating event identity/provenance failures from
   semantic evidence-grounding failures in a follow-up experiment?

## User review queue

- **57 extraction labels** in `runs/axiom/extraction_validation/labels.jsonl`;
  review the exact quotation and locator for each. The 18 ineligible labels and
  four exclusion disagreements deserve particular attention. The review packet
  is `runs/axiom/extraction_validation/REVIEW.md`.
- **36 expected-action/question labels** in the frozen benchmark manifest. They
  are marked `ai_draft_unreviewed`; inspect their source scope, expected
  conditions, gaps, applicability class and acceptable abstention before any
  correctness interpretation.
- **106 successful benchmark answers** in the shuffled, ungraded
  `review_packet.json` under the recorded benchmark run. Score before using
  `review_key.private.json`; style may still reveal the arm. Import grades only
  after noting reviewer identity, qualifications and uncertainty.

No reviewer is recorded. Keep all labels as agent-drafted until the user
finishes review; combustion-science interpretation remains provisional pending a
qualified domain reviewer. Eligibility/reuse remains unresolved under
[`docs/RULES_AND_ELIGIBILITY.md`](RULES_AND_ELIGIBILITY.md). No license grant or
competition eligibility is asserted.
