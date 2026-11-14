# Scientific methodology

This document states exactly how AXIOM derives, classifies and reports evidence.
It is written so that a reviewer can reproduce or challenge each step. All steps
described here are deterministic; no language model participates in condition
extraction, classification, coverage arithmetic, gap identification, proposal
generation or the Safety Critic pass.

## 1. Scope and non-claims

An AXIOM assessment answers one question:

> For each parameter of a hypothetical scenario, what does this specific corpus
> document about that parameter, and how does that documentation differ from the
> scenario?

It does **not** answer whether a design is safe. Specifically, AXIOM produces no
fire-risk score, probability of ignition, flammability rating, material
certification, operational recommendation or confidence percentage. The output
contains no aggregate "confidence" field.

## 2. Corpus boundary

The core corpus is fixed at load time from `data/processed/chunks.jsonl`:

- 12 ingested NASA documents;
- 294 passages;
- one `source_id`, `chunk_id`, page/section locator and SHA-256 digest per
  passage.

`load_chunks` recomputes every digest and rejects the corpus if any passage was
modified. The inventory hash in `data/processed/manifest.json` binds the
inventory (`data/sources.json`) to the corpus.

The corpus boundary is displayed in every assessment. A condition absent from
the corpus is reported as *not documented in the available corpus*, never as
*not tested by NASA*. The interface states this explicitly wherever an unknown
appears.

## 3. Condition extraction

`src/axiom/experiment_metadata.py` scans each passage sentence for nine fields:

| Field | Type | Canonical unit | Label |
|---|---|---|---|
| `gravity` | categorical | — | gravity regime |
| `fuel` | categorical | — | fuel or material |
| `geometry` | categorical | — | fuel geometry |
| `apparatus` | categorical | — | apparatus |
| `oxygen_percent` | numeric | % | oxygen concentration |
| `pressure_kpa` | numeric | kPa | pressure |
| `flow_cm_s` | numeric | cm/s | airflow speed |
| `ignition` | categorical | — | ignition method |
| `suppression` | categorical | — | suppression method |

Each extracted record stores:

- the quoted sentence (truncated at a word boundary to a fixed maximum),
- the source and chunk identifiers and locator,
- field, value and unit,
- an evidence status,
- a scope,
- the extraction rule identifier,
- `extraction = deterministic_pattern_v1`,
- `review_status = machine_extracted_not_human_reviewed`.

### Evidence status

| Status | Meaning |
|---|---|
| `reported` | The sentence reports a condition as part of the work |
| `proposed` | The sentence describes planned or future work |
| `background` | The sentence describes literature, context or a derived remark |

### Scope

Records may be scoped as `apparatus_capability`, `reported_limit` or
`instrument_metadata`. A record is **matching-eligible** only when:

```text
evidence_status == "reported"
and scope not in {"apparatus_capability", "reported_limit", "instrument_metadata"}
```

Ineligible records are still displayed, with their quote and reason, because
hiding them would make the corpus look cleaner than it is. They can never
produce a match.

## 4. Unit normalisation

Numeric scenario values are converted to the canonical unit before comparison.
The conversion table is explicit and closed; an unsupported unit is rejected, not
guessed.

| Field | Accepted units | Factor to canonical |
|---|---|---|
| `oxygen_percent` | `%`, `percent` | 1 |
| `pressure_kpa` | `kPa` | 1 |
| | `Pa` | 0.001 |
| | `atm` | 101.325 |
| | `bar` | 100 |
| | `psi` | 6.89476 |
| | `torr`, `mmHg` | 0.133322 |
| `flow_cm_s` | `cm/s` | 1 |
| | `mm/s` | 0.1 |
| | `m/s` | 100 |

Values are rounded to six decimals after conversion. No tolerance band is
applied: equality is checked with `abs(a - b) <= 1e-9` on converted values.

## 5. Four classifications

For each specified scenario field and each investigation, AXIOM assigns exactly
one classification.

### `exact_match`

A matching-eligible record reports a value equal to the scenario value after unit
normalisation, or a categorical canonical value equal to the scenario's canonical
value through the explicit alias table.

Alias examples: `PMMA`, `poly(methyl methacrylate)` and `cast PMMA` canonicalise
to `pmma`; `µg`, `micro-g` and `microgravity` canonicalise to `microgravity`.
The alias table is a fixed dictionary in `transferability.py`. There is no
fuzzy string matching.

### `partial_match`

No eligible record equals the scenario value, but at least one eligible reported
**range** contains it:

```text
range.min <= scenario_value <= range.max
```

The reason string says explicitly that range membership is not experimental
equivalence. A range's endpoints are not treated as separately tested values.

### `mismatch`

Eligible records exist for the field, but every reported value differs from the
scenario value, or the categorical value is different. The interface shows the
documented values and the nearest documented value.

### `unknown`

No eligible record exists for that field in that investigation. This happens in
two distinguishable ways:

- `basis = no_qualified_condition` — a mention exists but is planned, background,
  a limit or apparatus metadata; the mention is displayed but not used;
- `basis = not_documented_in_available_corpus` — no record exists at all for that
  field in that investigation.

**Unknown is never rewritten as a match.** There is no fallback similarity
threshold, no nearest-neighbour promotion and no model adjudication. A test
asserts that every `unknown` cell has an empty evidence list.

## 6. Coverage arithmetic

Coverage is computed over *scenario parameter × investigation cells*. If the
scenario specifies `p` parameters and the corpus yields `i` investigations, the
denominator is `p × i`.

Two numbers are reported and must not be conflated:

**Documented coverage**

```text
documented = cells classified exact_match, partial_match or mismatch
documented_percent = 100 × documented / denominator
```

Documented coverage means "the corpus says *something qualified* about this
parameter in this investigation". It does **not** mean the scenario is supported.
A mismatch is documented evidence and increases documented coverage.

**Alignment coverage**

```text
alignment = cells classified exact_match or partial_match
alignment_percent = 100 × alignment / denominator
```

Alignment coverage means "the corpus documents a value equal to, or a range
containing, the scenario value". It is an upper bound on documentary alignment,
not a probability that the scenario behaves as expected.

`alignment_numerator <= documented <= denominator` always holds. When the
denominator is zero, both percentages are `null`, not zero.

## 7. Evidence gaps

A gap is generated for a specified scenario field when no *direct* investigation
(for example, the microgravity solid-fuel group for a solid-fuel scenario) reports
an exact value. Each gap has one of seven kinds, ordered lexicographically by
documentation status:

| Order | Kind | Meaning |
|---|---|---|
| 0 | `no_documented_condition_in_corpus` | No ingested document reports the condition for any retrieved investigation |
| 1 | `combination_not_jointly_documented` | No single investigation reports exact values for all specified dimensions at once |
| 2 | `contextual_evidence_only` | Only investigations in a different combustion regime document it |
| 3 | `documented_outside_scenario_condition` | Documented, but at different values |
| 4 | `partial_documentation_only` | Only a reported range contains the value |
| 5 | `documented_only_as_plan_or_background` | Mentioned only as planned or background work |
| 6 | `documented_but_not_qualified` | Mentioned without a qualified reported value |

The ordering is a documentation-coverage ordering. It is **not** a scientific
importance score, severity score or priority for funding.

Every gap carries `what_is_missing`, `why_relevant`,
`what_cannot_be_established`, `documentation_status`, `possible_explanations`,
the contributing investigations and the relevant records. `possible_explanations`
always includes the possibility that the condition was tested outside this
corpus.

## 8. Proposal generation

At most three proposals are produced. Ordering is the gap order above, then the
field's fixed position in the field list, then the gap identifier. This is
lexicographic and reproducible.

Every proposal contains:

- `label` = `AXIOM PROPOSED — NOT EXECUTED OR VALIDATED NASA EXPERIMENT`;
- `research_question`, ending in a question mark;
- `hypothesis`, prefixed `Hypothesis (proposed, not observed)`, stating that
  direction and magnitude are unknown;
- `independent_variables`, `controlled_variables`, `dependent_variables`;
- `experimental_design`, which names the cited conditions and defers exact
  values, replication and safety controls to expert and facility review;
- `expected_contribution`, which cannot claim safety;
- `scientific_motivation` with `basis = documented_conditions_in_available_corpus`
  and a list of cited records;
- `proposed_values`, each marked `user_scenario_value_not_measured`;
- `unresolved_limitations`;
- `priority`, exposing the ordering criteria.

Constraints enforced by construction and by tests:

- no numeric range, sample size, measurement or outcome is invented;
- scenario numbers appear only as user inputs, labelled as such;
- every cited record resolves to a chunk and its quoted text is a substring of
  that chunk;
- prohibited claim patterns (`is proven`, `guarantees`, `flight-ready`,
  `is safe`, and similar) are flagged by the deterministic critic before a
  proposal is released.

## 9. Safety Critic

The deterministic critic audits generated statements before display. It withholds
or qualifies text that:

- asserts a strong conclusion without support (`is proven`, `guarantees`,
  `is safe`, `flight-ready`);
- contains a numeric literal without a citation;
- uses a unit that was not resolved;
- attributes a condition the corpus classifies as unknown or mismatched;
- treats absence of documentation as a negative experimental result;
- makes an operational inference that requires expert review.

The critic returns counts of withheld, qualified and supported statements. It is
not a model, produces no confidence value, and never upgrades an unknown
classification.

## 10. Determinism and reproducibility

- Identifiers are derived from content hashes, not random state, except the
  assessment `scenario_id`, which is a UUID used only as a storage key.
- Sorting is explicit at every aggregation point (field order, investigation
  identifier, gap order).
- No network call occurs during assessment, planning, catalog building or the
  critic pass.
- `assess` on the same corpus and the same scenario returns the same coverage,
  classifications, gaps and proposals.

## 11. Reference validation

The repository test suite reproduces, among other properties:

- all four classifications are reachable and unknown never carries evidence;
- every quoted condition is a substring of the chunk it cites;
- every proposal citation resolves to a real chunk;
- proposal labels contain `PROPOSED` and `NOT EXECUTED`;
- unit conversion is exact for the table above and rejects unsupported units;
- scenario save, reopen, export and atomic-write behaviour;
- the shipped corpus really has 12 documents and 294 passages.

Tests are the executable form of this document. See
[docs/VALIDATION.md](VALIDATION.md) for the recorded run.
