# Mission scenario stress test and next-experiment planner

Implemented with AI coding assistance; no
human scientific review, experimental validation or safety certification has
been performed.

This document describes two connected capabilities in AXIOM:

1. **Mission scenario stress test** — asks how far the evidence in the available
   corpus travels to a hypothetical scenario.
2. **Next experiment planner** — turns identified documentation gaps into
   proposed research concepts that are explicitly not executed and not
   validated.

Both are deterministic. No language model participates in extraction,
classification, coverage arithmetic, gap identification, proposal generation or
the Safety Critic audit.

## What the assessment is not

- It is **not** a fire-risk prediction, ignition probability or safety score.
- It is **not** a safety certification, material approval or operational
  recommendation.
- It does **not** establish that a scenario is safe because conditions match.
- It does **not** establish that NASA never tested a condition because the
  corpus is silent.

Condition comparison is necessary but not sufficient for transferability.
Apparatus, scale, ignition protocol, measurement definitions and test matrices
can still differ even when reported conditions agree.

## Corpus and provenance

The assessment runs over the ingested corpus only. At the time of writing that
is **12 NASA documents, 294 passages, 5 investigation groups and 239 extracted
condition records** (qualified and unqualified). The corpus is not a complete
NASA archive; a missing condition may exist in another publication, report or
data archive.

Every extracted record carries:

- `source_id`, `chunk_id` and `locator` (PDF page or equivalent),
- an exact `quote` from the passage,
- the original reported value and unit, plus a canonical unit,
- `scope` (for example `individual_test`, `experiment_range`,
  `apparatus_capability`, `instrument_metadata`),
- `evidence_status` (`reported`, `proposed`, `background`, …),
- `matching_eligible`, and
- `review_status = machine_extracted_not_human_reviewed`.

Records are deduplicated per source, field, canonical value and evidence
status. A record is discarded if its quotation cannot be found in the source
passage. The AI-draft condition records under `data/` are not used for matching;
they remain display-only.

## Deterministic metadata extraction

`src/axiom/experiment_metadata.py` applies auditable regular expressions to
sentences in each passage. It extracts:

| Field | Examples of accepted evidence |
| --- | --- |
| `gravity` | microgravity, terrestrial, lunar, Martian, unspecified partial gravity |
| `fuel` | PMMA, methanol, heptane, SIBAL/cotton-fiberglass, Nomex, thermoplastic |
| `geometry` | rod, cylinder, slab, film, fabric sheet, thick sample, droplet |
| `apparatus` | MSG, CIR, MDCA, wind tunnel, flow duct, Saffire Flow Unit, Cygnus, ZGRF |
| `oxygen_percent` | `21% O2`, `30 percent oxygen`, oxygen ranges |
| `pressure_kpa` | atm/kPa/Pa/bar/torr/mmHg/psi, converted to kPa |
| `flow_cm_s` | cm/s, mm/s, m/s in an explicit airflow context, converted to cm/s |
| `temperature_k` | K, °C, °F applied to an imposed test/chamber/preheat temperature, converted to K |
| `ignition` | hot wire, ignition coil, spark, radiant, piloted, … |
| `suppression` | inert gas, water mist, vacuum, … (lexicon-based) |

Unit conversion is exact arithmetic (for example `1 atm = 101.325 kPa`). A
range is stored as `{min, max}`. Repeating-unit ranges such as
`40 cm/s down to 1 cm/s` are treated as one range, not as two individually
tested points.

Conservative exclusions prevent common false matches:

- flame-spread and burning rates are not treated as imposed airflow;
- instrument resolution is not a test condition;
- limit outcomes and blow-off results are not setup values;
- flame, exhaust, wall and outlet temperatures are not imposed test temperatures;
- percentages attached to CO2, N2 or other species are not inferred as oxygen;
- planned-work wording is stored as `proposed` and cannot match;
- background wording is stored as `background` and cannot match;
- apparatus capability is visible but cannot match.

This is a pattern extractor, not a semantic reader. Sentence-level rules can
miss conditions expressed only in tables, figures or long noun phrases. Every
record therefore remains machine-extracted and requires review before use as a
scientific claim.

### Investigation grouping

`_GROUPS` in `experiment_metadata.py` is a small curated alias table, not a
measurement. In the current corpus it yields five active groups:

| Investigation ID | Label | Domain | Curated behaviours |
| --- | --- | --- | --- |
| `FLEX` | FLEX droplet combustion | droplet combustion | ignition, extinction, burning rate |
| `BASS-II` | BASS-II solid-fuel flame spread | solid-fuel flame spread | ignition, flame spread, extinction, flame growth |
| `BASS-GC` | BASS-II ground comparison | solid-fuel flame spread | ignition, flame spread, extinction, flame growth |
| `SAFFIRE` | SAFFIRE large-scale flammability | large-scale solid flammability | flame spread, fire growth, material flammability |
| `SAFFIRE-V` | SAFFIRE-V large-scale flammability | large-scale solid flammability | flame spread, fire growth, material flammability |

Aliases such as `BASS`, `BASS/BASS-II` and
`BASS-II / ground comparison` are mapped explicitly. Sources with no extracted
condition do not receive invented metadata and are not represented as an empty
investigation.

## Scenario input

A scenario request is a JSON object:

```json
{
  "scenario": {
    "gravity": "microgravity",
    "fuel": "sibal fabric",
    "geometry": "fabric sheet",
    "oxygen_percent": {"value": 21, "unit": "%"},
    "pressure_kpa": {"value": 101.325, "unit": "kPa"},
    "flow_cm_s": {"value": 20, "unit": "cm/s"}
  },
  "interest": "flame_spread",
  "description": "Hypothetical crew-cabin fabric scenario.",
  "save": true
}
```

Rules:

- A blank or absent field stays **unknown**. It is never defaulted and never
  treated as a match.
- Numeric values require an explicit `{value, unit}` object. Accepted units are
  converted to `%`, `kPa` and `cm/s`.
- Values must be finite and within physical bounds
  (`oxygen 0–100 %`, `pressure > 0`, `flow ≥ 0`).
- Unknown fields, unknown units, non-boolean `save` values and oversized
  descriptions fail closed with a validation error.
- The original user units are retained in `scenario_input`; comparison uses the
  normalized `target`.

## Four classifications

Each specified field is compared separately for each investigation.

| Classification | Meaning |
| --- | --- |
| `exact_match` | A qualified reported value equals the scenario value after unit conversion, or a canonical categorical alias is identical. |
| `partial_match` | The scenario value lies inside a reported test **range**, but no individually reported point at that value was found. Range membership is not experimental equivalence. |
| `mismatch` | Qualified documented values differ from the scenario value. |
| `unknown` | No qualified reported value exists in the available corpus for that field/investigation. |

`unknown` is never rewritten as a match. It means “not documented here”, not
“NASA never tested it”.

There is no similarity score, invented tolerance, fuzzy numeric threshold or
model judgement. Categorical matching uses an explicit alias table; a term
absent from that table can only match identical user text.

### Direct versus contextual relevance

`interest` selects a fire behaviour. An investigation is **direct** when its
curated behaviour list contains that interest. Otherwise it is **contextual**:

- a condition match in a contextual investigation remains visible but cannot
  become direct support;
- a contextual exact match still leaves an evidence gap;
- an investigation with no specified interest is treated as unclassified, not
  as automatically direct.

This separation prevents, for example, a droplet-combustion condition match from
being presented as direct evidence about fabric flame spread.

### Investigation applicability

Per investigation, the displayed applicability is:

- `outside_documented_conditions` if any specified field is a mismatch;
- `partially_documented` if there is at least one exact/partial match and at
  least one unknown;
- `documented_alignment` if all specified fields are exact/partial matches;
- `no_documented_conditions` if all specified fields are unknown;
- `not_assessed` when no field was specified.

Applicability is a description of documentation relationships, not a safety
judgement.

## Coverage arithmetic

Coverage is counted in **scenario-parameter × investigation cells**.

For `S` specified scenario fields and `I` compared investigations:

```text
denominator        = S × I
documented_numerator = cells classified exact_match, partial_match or mismatch
alignment_numerator  = cells classified exact_match or partial_match
documented_percent   = 100 × documented_numerator / denominator
alignment_percent    = 100 × alignment_numerator / denominator
```

Unknown cells count in the denominator and are not documented.

- **Documented coverage** answers: in how many cells does the corpus contain
  any qualified value at all?
- **Alignment coverage** answers: in how many cells does the documented value
  equal or contain the scenario value?

Neither percentage is a probability, confidence score or safety measure. A high
documented coverage can coexist with low alignment, because most documented
values may differ from the scenario.

## Evidence gaps

A field is a gap when no **direct** investigation has an exact match. Lower
evidence levels produce narrower gap kinds. No kind asserts that an experiment
was never conducted.

| Gap kind | Meaning |
| --- | --- |
| `no_documented_condition_in_corpus` | No qualified value for the specified field appears for any compared investigation. |
| `combination_not_jointly_documented` | No single direct investigation is exact on **all** specified fields at once, even though different investigations cover parts of the combination. |
| `contextual_evidence_only` | Exact/partial documentation exists only in investigations in another combustion regime or behaviour. |
| `documented_outside_scenario_condition` | The field is documented, but at values different from the scenario value. |
| `partial_documentation_only` | The scenario value lies only inside a reported range; no individually reported point was found. |
| `documented_only_as_plan_or_background` | The value appears only in planned-work or background wording. |
| `documented_but_not_qualified` | A mention exists but is not a qualified reported test condition. |

Each parameter gap reports:

- what is missing and why it matters;
- what the corpus cannot establish;
- documentation status;
- which investigations matched, differed or were silent;
- quoted records where available;
- possible explanations and the corpus boundary.

Possible explanations for absence are listed together and are not resolved:

1. no such experiment was conducted;
2. an experiment exists but is not among the ingested documents;
3. the condition is expressed in prose or a table that the extractor missed;
4. the condition was reported with a non-comparable unit or definition.

This is the honest answer to “gap versus missing documentation”: the system can
distinguish documentation states (absent here, elsewhere values, range-only,
planned-only, contextual, unqualified, not joint), but it **cannot** distinguish
“never investigated” from “investigated but undocumented in this corpus”. It
does not pretend to.

The combination gap is added when at least one field is specified and no direct
investigation is exact on every specified field. It is a separate gap with
`field: null` and a per-investigation coverage summary.

## Next experiment planner

The planner creates at most three proposals, and may create none. A proposal is
only generated from an identified gap.

Each proposal contains:

- a prominent label:
  `AXIOM PROPOSED — NOT EXECUTED OR VALIDATED NASA EXPERIMENT`;
- the gap it addresses and the gap kind;
- a research question and a scientific motivation with cited records;
- a hypothesis explicitly marked `(proposed, not observed)`;
- independent, controlled and dependent variables;
- an experimental-design outline;
- expected contribution and unresolved limitations;
- source identifiers;
- the user's scenario values marked `user_scenario_value_not_measured`;
- a priority record.

Numeric discipline:

- No parameter range, sample size, measurement target or expected outcome is
  invented.
- The only numbers in proposal prose are the user's scenario value, cited
  documented values, and range endpoints from cited records.
- Statements are phrased as “could”, “may” and “unknown until performed”.

Priority is **lexicographic**, not a scalar score. The ordering of gap kinds is:

```text
no documented condition
→ combination not jointly documented
→ contextual evidence only
→ documented outside scenario condition
→ partial documentation only
→ planned/background only
→ unqualified mention
```

Within the same gap kind, fields follow the fixed `FIELDS` order and then
`gap_id`. This is a documentation-coverage ordering, not scientific importance.

Proposals are labelled as requiring qualified scientific and facility-safety
review before execution.

## Safety Critic audit

`audit()` is a deterministic rule pass over the generated assessment. It is not
a combustion-scientist review.

For every gap statement it withholds when the text:

- treats absence as a negative experimental result
  (`absence_treated_as_negative_result`), or
- contains an unsupported safety or proof claim
  (`unsupported_strong_claim`).

For every proposal it withholds when:

- the proposal is not clearly labelled, or its hypothesis is not marked proposed;
- the hypothesis or expected contribution contains an unsupported strong claim;
- a citation's chunk/quote pair is not present in the compared records;
- the linked gap is unknown;
- the proposal duplicates an existing direct exact match;
- the text introduces a number that is neither a scenario value nor a cited
  documented value (`unsupported_numeric_value`).

A proposal whose motivation has no cited documented condition is **qualified**,
not silently accepted.

For every investigation it reports:

- `qualified` when conditions align but the investigation is contextual;
- `qualified` when at least one condition differs;
- `qualified` when no qualified condition is documented;
- `supported` otherwise, without asserting safety.

The audit summary counts supported, qualified and withheld checks. Its
`prohibited_conclusion` states that no output establishes spacecraft fire
safety, material approval or an operational firefighting decision.

## API

All endpoints are local, same-origin and JSON-only. Existing host, origin and
request-size guards are reused. No model is constructed.

### `GET /api/scenario-metadata`

Returns field definitions, accepted units, documented-value suggestions,
interests, synthetic presets, corpus counts and notices.

Documented values are suggestions from the available corpus, not required
inputs.

### `POST /api/scenario-assess`

Request body as shown above. Returns the full assessment: normalized and
original targets, per-investigation comparisons with quotations and locators,
coverage, gaps, proposals, Safety Critic checks, retrieval/corpus scope,
limitations and `saved_locally`.

When `save` is true and persistence succeeds, the assessment is written under
`runs/scenarios/<scenario_id>.json`. If saving fails, the response still
returns the assessment with `saved_locally: false` and a `save_error`.

### `POST /api/scenario-plan`

```json
{"scenario_id": "…", "gap_ids": ["gap-combination"]}
```

Reuses the stored assessment; it does not re-run retrieval or generation.
`gap_ids` is optional and filters both gaps and proposals. The response is
labelled `AXIOM PROPOSED RESEARCH CONCEPTS — NOT EXECUTED OR VALIDATED`.

### `GET /api/scenarios?limit=20&offset=0&query=…`

Lists bounded summaries (description, interest, fields, documented coverage,
alignment coverage, applicability counts). `limit` is 1–100, `offset` is
nonnegative, `query` is at most 500 characters.

### `GET /api/scenarios/<scenario_id>`

Returns one saved assessment. Path traversal, missing identifiers and malformed
records fail closed.

## Persistence

There is no SQL database and no migration. Scenario assessments use the
existing bounded JSON record store:

```text
runs/scenarios/<scenario_id>.json
```

Writes are atomic (temporary file, `fsync`, `os.replace`), records are limited
to 2 MiB, duplicate JSON keys and non-finite numbers are rejected, and read
paths are validated against traversal. Saved assessments are immutable
snapshots of one comparison; they are not revalidated when the corpus or
extractor changes.

## Dashboard

The **Mission scenario** view keeps the existing visual identity:

- green/teal = exact alignment;
- amber = partial/qualified;
- red = mismatch/withheld;
- grey = unknown/unreported.

The view contains:

1. a scenario builder with blank-as-unknown fields, units, an interest selector,
   three clearly labelled synthetic presets and an optional local save;
2. summary statistics and an explicit coverage definition;
3. an evidence coverage map per field;
4. a parameter comparison matrix;
5. expandable investigation cards with reasons, exact quotations, source IDs,
   chunk IDs, locators and unqualified mentions;
6. a Safety Critic panel;
7. gap cards and proposal cards with evidence and limitations;
8. export to JSON, saved-assessment list and reopening.

After the first assessment, changing a field triggers a debounced automatic
re-assessment (450 ms). Automatic assessments never save. A visible banner
reports what changed: coverage percentages, new or closed gaps, and new or
dropped proposals. The explicit **Assess scenario** button honours the save
checkbox.

### Demonstration

Start the dashboard (`python -m axiom serve --port 8767`) and open
**Mission scenario**.

1. Choose **Crew cabin · fabric sample**.
2. Observe the initial result on the current corpus snapshot:
   documented coverage 90.0 %, alignment 53.3 %, one combination gap and one
   combination proposal.
3. Change oxygen from 21 % to 30 %.
   The banner reports alignment 53.3 % → 50.0 %, a new oxygen gap and a new
   oxygen proposal.
4. Change airflow from 20 cm/s to 80 cm/s.
   Alignment falls again and an airflow proposal appears.
5. Change pressure to 200 kPa.
   Pressure documentation is reported as outside the scenario condition and a
   pressure proposal is added (subject to the three-proposal limit).
6. Select the **Low-pressure thermoplastic** preset to see a different
   combination and gap set, with pressure deliberately unknown.
7. Tick **Save this assessment locally**, click **Assess scenario**, then reopen
   it from **Saved scenario assessments**.

These numbers are observations from the current corpus and extractor, not
benchmark scores. They will change if the corpus, alias table or extraction
rules change.

## Tests

New and extended tests cover:

- `tests/test_experiment_metadata.py` — unit conversion, repeated-unit ranges,
  species exclusion, planned/background exclusion, instrument metadata,
  rate-versus-airflow exclusion, alias grouping and quotation provenance;
- `tests/test_transferability.py` — normalization, fail-closed validation, four
  classifications, contextual relevance, coverage arithmetic, every gap kind,
  combination gap, proposal labelling, no invented ranges, lexicographic
  priority and critic withholding;
- `tests/test_scenario.py` — catalog, orchestration, parameter-change
  sensitivity, unknown handling, empty scenario, validation, persistence,
  planning, search/pagination and malformed records;
- `tests/test_server.py` — metadata/assess/plan/list/open endpoints, no model
  construction, host/origin guards, validation and missing-record handling.

Full suite at implementation time: **491 tests, OK, 5 skipped**.

## Limitations

- The corpus is 12 documents and 5 investigation groups. Absence is
  corpus-bounded, not archive-complete.
- Extraction is sentence-level regex. Tables, figures, footnotes and unusual
  phrasing can be missed; inferred meaning is not verified.
- All condition records are machine-extracted and not human-reviewed.
- Matching uses exact equality and range containment. No experimental tolerance
  or measurement uncertainty is invented.
- Categorical aliases, investigation grouping and behaviour lists are curated
  engineering metadata, not measurements.
- Direct/contextual classification is a curated keyword mapping, not a
  validated model of scientific relevance.
- Conflicting reports across sources are displayed but not adjudicated.
- No temporal/version tracking distinguishes preliminary, revised or withdrawn
  findings.
- Condition agreement does not establish transferability; apparatus, scale,
  ignition protocol and diagnostics may differ.
- An exact quotation establishes what the source says, not that a new
  inference about the scenario follows from it.
- Proposals are concepts only. They have no approved parameter ranges, sample
  sizes, diagnostics, facility review or safety approval.
- Saved assessments are snapshots and are not revalidated against later corpus
  changes.
- The dashboard is a single-user local prototype; its security boundary is the
  loopback host/origin guard, not multi-user authentication.
