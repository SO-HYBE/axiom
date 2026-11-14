# Data and evidence provenance

## Identity layers

- **Resource ID** identifies one of the ten challenge URLs (`R1`–`R10`). It is
  an inventory identity, not proof of acquisition.
- **Source ID** identifies an item in the existing `data/sources.json` or
  named-source inventory (for example, `psi-69` or `ntrs-20160000593`).
- **Document or dataset identity** is the publisher's identifier: PSI accession
  and version, NTRS citation ID, or a stable source document URL.
- **Chunk/evidence ID** identifies a text passage produced from a source. The
  passage retains source ID, title, canonical URL, locator, text digest and
  evidence classification. A citation resolves through that source identity.
- **Asset provenance** records original URL, final URL, retrieval time, byte
  count, content type, SHA-256 and local relative path. Hashes detect accidental
  local changes; they do not establish publisher authenticity or scientific
  truth.

The existing corpus chunk schema and named-source snapshot format are the
authoritative implemented formats. Do not infer a missing resource ID from
topical similarity. Where a challenge resource and an existing source overlap,
maintain both identities and explicitly link them rather than relabeling old
acquisitions after the fact.

## Lineage and citation resolution

The core NTRS acquisition path in `src/axiom/ingest.py` stores PDF-derived
passages with page locators and digests. Named source acquisition in
`src/axiom/benchmark_named_sources.py` stores raw bytes and `.provenance.json`
sidecars, then creates selected section-level passages. Existing retrieval
citations refer to source ID, chunk ID, URL and locator. For PSI, source URL,
accession, DOI and version are retained in the named-source inventory/derived
records; PSI file listing entries are not indexed as measurement records.

Do not overwrite raw source bytes or rewrite original acquisition timestamps.
If a source is acquired again at another version, preserve it as a new version
with its own timestamp and hash. Derived text must remain reproducible from the
stored original bytes and extraction code/version.

## Metadata provenance vocabulary

Use these distinctions at field level:

| State | Meaning |
|---|---|
| `SOURCE_REPORTED` | A value is explicitly present in source text/table and quoted with a locator. This is a source statement, not independent validation. |
| `AUTOMATICALLY_EXTRACTED` | Software extracted a source-reported candidate; preserve the quote and exact locator. |
| `HUMAN_REVIEWED` | A named human reviewer checked the candidate against the original. Do not assign this state to agent output or user ownership alone. |
| `NOT_STATED` | The inspected source scope does not state the field. Store null, never zero or a plausible default. |
| `AMBIGUOUS` | The source statement or its applicability to an experiment is unresolved. Preserve the text and do not select a value. |

The repository's existing experiment metadata uses legacy evidence statuses
such as `reported_test_condition`, `proposed`, and `background` and marks its
records `machine_extracted_not_human_reviewed`. Do not reinterpret those legacy
labels as human review. A source quote proves only that the passage was found;
it does not establish that a claim logically follows from the source.

## Claim and assurance traceability

AXIOM execution traces record evidence IDs on retrieval/link events and
evaluate process properties over event sequences. This can establish that a
claim references a particular retrieved source record and locator in a trusted
trace. It cannot decide whether the source semantically supports the claim or
whether conditions transfer to a new scenario. Successful acquisition or
parsing is not scientific validation. Missing or ambiguous source metadata
must remain unknown in applicability and claim assurance.
