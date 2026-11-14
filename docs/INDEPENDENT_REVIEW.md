# Independent scientific review of AXIOM answers

This packet contains provisional model outputs from the AXIOM research system.
No independent grades have been supplied. The solo participant is
responsible for the product and usability; this scientific review is intended
for someone with relevant combustion or experimental-science expertise.

## Files and scope

- `review_packet.json`: shuffled answers, question wording, named source scope,
  reported abstention, released claims and citations. System labels and critic
  verdicts are removed. Every `grading` value starts as null.
- `corpus_snapshot.json`: exact locally extracted source passages, locators and
  hashes from the frozen run. Consult the original primary URLs when extraction,
  tables, figures, conditions or interpretation are uncertain.
- `benchmark_sources.json` and `sources.json`: primary URLs, evidence roles and
  rights records. Catalog text describes objectives or listed files; it is not
  a measurement table. Raw experimental datasets were not imported.

The owner's `review_key.private.json` is deliberately excluded. Do not request
that mapping while grading. Text style, citations and withholding language may
still reveal a system, so this is not guaranteed blinding. The benchmark's
expected answers and AI draft rubrics are also excluded from this packet.

## Review procedure

Record your name or stable identifier, relevant qualifications, review date,
conflicts of interest, whether you helped develop AXIOM, and any use of automated
assistance. These declarations must not be presented as independently verified
credentials. Do not copy a model's support or safety judgments into grades.

For each item, inspect the entire answer, including explanations accompanying
an abstention. The structured claim list may omit assertions or combine several
claims. Record any split or correction separately, preserving the original item
and answer. Items needing normalization remain pending until their audited claim
list can be aligned with the evaluator. Do not silently grade only the easiest
subset of assertions.

Within the question's named source and section, assess:

1. Does the full claim follow from the evidence, with correct quantities, units,
   negation, materials, atmosphere and experimental context?
2. Does each citation identify the correct source and located passage, and does
   that passage support the entire claim? A matching quote establishes textual
   traceability, not scientific entailment.
3. Does the answer assert unsupported transfer to another fuel, flow, pressure,
   oxygen level, gravity setting, spacecraft or operational safety decision?
4. Is answering or withholding the requested conclusion justified? Distinguish
   an unnecessary abstention from an appropriately bounded answer or rejection
   of a false premise. A failed provider call is not an answer.

Give an explicit rationale and unresolved questions. Keep uncertainty pending
when the named source cannot settle an interpretation. Do not infer measured
conditions from a program overview, an objective, a file name, or a missing field.

## Grading and later import

The existing evaluator accepts boolean `supported`, `citation_valid` and
`unsafe_extrapolation` values for each audited claim, plus a boolean or unresolved
null `correct_abstention` for each answer. An uncited claim has
`citation_valid: false`. The abstention grade assesses whether the decision was
appropriate, regardless of whether the system answered or abstained.

Return completed grades against the packet's `item_id`, together with rationale,
qualifications and any atomization edits. The owner reconciles the audited claim
list, uses the private mapping, verifies the prediction hashes, and converts
reviewed items into the annotation contract in `docs/EVALUATION.md`. Items with
missing or unalignable grades stay ungraded. Partial review reports its exact
denominators and exclusions. No score should imply that all cases were reviewed.

The current questions are AI drafts, the public test split was visible during
development, and source documents overlap across splits. A review of this run
would therefore support an exploratory comparison on these cases, not a safety
certification or evidence of performance on unseen scientific literature.

## Import a completed packet

The owner can import a completed packet directly, without manually aligning
system names. Preserve each item and change only its `grading` field. Add these
top-level declarations, completed by the actual reviewer: `reviewer`,
`qualification`, ISO `reviewed_at`, `independence_declaration`, `independent: true`,
`human_review: true` and `review_method: "human"`. Disclose any assistance in
`assistance_disclosure`. These declarations are self-reported, not verified
credentials. Leave them unset in an unreviewed template.

```powershell
python -m axiom benchmark-review-import RUN_ID completed-review-packet.json
```

The importer checks the private mapping, original prediction hashes and every
question, answer, source scope, claim and citation. Changed outputs or duplicate
items are rejected. A null grade remains ungraded; any unknown claim label keeps
that item pending. Use `grading: {"status":"requires_atomization","reason":"..."}`
when assertions need splitting or correction before reliable claim alignment.

Each import creates its own `reviewed_imports/IMPORT_HASH/` directory containing
annotations, a reviewed report and a private reviewer record. Original runs,
packets and reports are not overwritten. Partial imports are not silently merged.
Automated model grades cannot be imported as declared human review. Report the
actual reviewed denominators; missing grades never count as passing results.

## Export a standalone public handoff

From the owner project directory, export the saved run with:

```powershell
python -m axiom benchmark-review-bundle RUN_ID
```

Replace `RUN_ID` with the actual saved benchmark ID. The owner directory needs
the run's authoritative records and its matching `review_packet.json` and
`review_key.private.json`. If both packet and mapping are absent, the exporter
creates them together; an incomplete pair or stale mapping fails closed. A
source checkout or release that excludes the private mapping cannot re-export
an existing packet with its original identities. Keep that mapping in the owner
workspace for later import, and do not send it to the reviewer.

The command writes `runs/benchmarks/RUN_ID/review_bundle.zip`, a public template
and a sibling bundle manifest. The ZIP has a fixed allowlist:

- `review_packet.json` and `review_packet.template.json`;
- the exact `corpus_snapshot.json` frozen for generation;
- `sources.json` and `benchmark_sources.json`, identifying rights and provenance
  at export;
- this guide, a handoff README and `bundle_manifest.json` with file hashes.

The private mapping, expected answers, draft rubrics and failed job bodies are
excluded. The public ZIP is sufficient for a reviewer to inspect the answers,
source text and instructions without access to the owner checkout. Its hashes
check local file consistency, not publisher authorship or scientific correctness.
Writing style may still identify a system; the export does not promise perfect
blinding.

Leave `review_packet.json` unchanged. Make a separate copy of the template for
completed review. It begins with null reviewer declarations and null grades;
the `review_method: "human"` field specifies the intended process, not a claim
that human review has occurred. Preserve every `item_id`, question, answer,
scope, claim and citation. Fill only actual reviewer declarations and item
`grading` fields. The exporter preserves existing item IDs and refuses to
overwrite an edited template; never regenerate a packet after review begins.

Review can be deferred until a suitably qualified reviewer is available. The
solo participant can continue engineering and usability work without grading
unfamiliar combustion science. No model-generated or assumed grade fills that
gap. Once review is completed, return the completed template to the owner and
use the import command above; incomplete or unalignable items remain ungraded.
