# Safety boundaries and limitations

AXIOM is a research and evidence-traceability tool. It is **not** a safety
analysis tool, a flammability certification system, a fire-risk predictor or an
operational decision aid for a spacecraft.

## Hard boundaries

1. **No fire-risk prediction.** AXIOM never outputs a probability of ignition,
   a flammability rating, a time-to-flashover estimate or an aggregate risk
   score.
2. **No confidence score.** Coverage percentages count documentation cells.
   They are not model confidence, evidence strength or probability of
   correctness. A mismatch increases documented coverage while decreasing
   alignment coverage.
3. **No safety certification.** A documented match means the corpus reports an
   equal test condition. It does not mean a material, configuration or
   procedure is safe.
4. **No flight recommendation.** Nothing in the output is approved for flight,
   operations or crew procedure.
5. **No executed experiments.** Every proposal is labelled
   `PROPOSED — NOT EXECUTED`. A proposal is a research concept, not a completed
   study and not a result.
6. **No invented values.** Missing table values, ranges, measurements, sample
   sizes and outcomes remain absent. Where a value is unknown, the output says
   so.
7. **No absence-as-negative-result.** An unreported condition is described as
   *not documented in the available corpus*. It is never described as *NASA
   never tested it*.
8. **No silent model judgement.** Classification, coverage, gap identification,
   proposals and the Safety Critic are deterministic code paths. Model output is
   optional and is itself checked.

## Scientific limitations

### Corpus

- The core corpus contains **12 NASA documents and 294 passages**. It is a
  documented subset, not a complete archive of microgravity combustion
  research.
- It is **not** a verified transcription of an official challenge dataset list.
  BASS-II, FLEX, SAFFIRE and PSI were selected as comparable NASA resources.
- Three NTRS records are marked `review_required` and are not ingested. Their
  content is therefore absent from every assessment.
- One large FLEX report is used through named-source text rather than the full
  PDF.

### Extraction

- Condition metadata is **machine-extracted** (`deterministic_pattern_v1`) and
  is **not human-reviewed**.
- Values that appear only in figures, or in tables whose headers do not survive
  text extraction, may be missed.
- A sentence may describe planned work, literature context or a reported limit.
  Evidence status is assigned by pattern, and misclassification is possible.
- Quotes are truncated at a word boundary; a truncated quote may omit a
  qualifier that appears later in the sentence.

### Comparison

- Numeric matching is exact equality after unit conversion, or containment in a
  reported range. No tolerance band is invented.
- Range membership is **not** experimental equivalence.
- Categorical matching relies on a fixed alias table. A synonym outside the
  table produces a mismatch, not a semantic match.
- Condition comparison is necessary but not sufficient for transferability.
  Apparatus, scale, ignition protocol, ventilation geometry and measurement
  definitions can still differ.
- Only reported test conditions are matching-eligible. Planned matrices,
  apparatus capability statements and reported limits are displayed but cannot
  produce a match.

### Proposals

- Proposals are generated from documentation gaps, not from a physical model.
- The ordering is lexicographic by documentation status. It is not a
  scientific-importance, feasibility or cost ranking.
- No expected outcome, parameter range, sample size or measurement is asserted.
- A qualified combustion scientist and a facility safety review are required
  before any proposed experiment is attempted.

### Evaluation

- The saved benchmark run records how three system configurations behaved on 36
  questions. It contains **zero independent scientific grades**.
- Claim counts, abstentions and latency are observations, not accuracy.
- Latency comparisons are confounded by caching and provider retries.
- The presence of a quotation proves text provenance, not that a claim follows
  from the quotation.

## Data and rights limitations

- NASA documents retain their own terms. They are not relicensed under MIT.
- Three inventory-only sources are rights-restricted and are not redistributed.
- Raw PDF bytes of the core corpus are excluded; only processed passages,
  locators and hashes are shipped.
- Saved model output is recorded behaviour, not NASA or vendor endorsement.

See [DATA_SOURCES.md](DATA_SOURCES.md) and
[../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## AI assistance and provenance

- The project was built by a solo participant with AI coding agents assisting
  implementation, source research, evaluation design and review.
- No human scientific review has been claimed or recorded.
- Actual creation dates and commit history are preserved in
  [../PROJECT_WORK.md](../PROJECT_WORK.md).
- Competition eligibility and reuse permission are unresolved. See
  [RULES_AND_ELIGIBILITY.md](RULES_AND_ELIGIBILITY.md). This repository does not
  assert eligibility.

## Known defects and open work

- Condition extraction recall is unmeasured. No gold-standard annotation set
  exists for the 12 documents.
- The dashboard's accessibility has been checked manually at desktop, tablet and
  phone widths, but no automated WCAG audit is included.
- The application is single-user. There is no authentication, rate limiting or
  account model, because it is designed to run locally or behind a trusted
  proxy.
- Saved scenarios are validated on read but not schema-migrated. A future
  schema change would need a migration step.
- The public deployment has not been performed. See
  [DEPLOYMENT.md](DEPLOYMENT.md) for verified status.

## Reporting a problem

Open an issue describing the scenario, the expected classification, the actual
classification, the source identifier and the chunk identifier. Do not include
API keys, personal information or restricted publication text.
