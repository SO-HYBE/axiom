# Experimental metadata extraction

## Implemented baseline

`src/axiom/experiment_metadata.py` extracts candidate conditions from quoted
sentences in the existing research corpus. It retains source/chunk identity,
the exact quote, locator, field, extraction method and a provisional evidence
status. The current corpus contains 239 machine-extracted records across five
investigation groups, all marked `machine_extracted_not_human_reviewed` in the
existing validation artifacts. They are not human-reviewed labels.

The core applicability model supports condition fields including oxygen,
pressure, airflow, gravity, fuel, material, geometry, configuration and
temperature. A missing or unclear field remains unknown; values are not filled
from scientific expectations. Applicability results compare only recorded
fields and are not proof of physical transferability.

## Required field record

For any new resource-derived value, retain at least:

- source/resource/document identifier and source URL;
- source-reported value and exact quotation;
- page, table, row, section, or timestamp locator;
- normalized value and unit only when conversion is deterministic and
  unambiguous;
- extraction method and software version;
- provenance state (`SOURCE_REPORTED`, `AUTOMATICALLY_EXTRACTED`,
  `HUMAN_REVIEWED`, `NOT_STATED`, or `AMBIGUOUS`);
- validation state and reviewer identity/date only when a real review occurs.

Do not confuse those provenance states with status of a physical experiment.
For example, an automatically extracted value may be an explicitly reported
test condition but remains unreviewed by a human. A value mentioned in a plan,
background section, incident account, model input, or catalogue description is
not automatically an experimental measurement.

## Scope distinctions

Only controlled research sources can provide experimental-condition evidence.
PSI catalog records can identify investigations, objectives, versions, and
file listings but are not measurements. Apollo 1 is a ground-test incident;
Apollo 13 is an oxygen-tank incident; Mir is an operational fire account.
ScienceCasts is educational narration. NASA Spinoff pages describe technology
transfer. Keep those categories separate in metadata and retrieval. A quote
from an incident or educational source cannot be relabeled as a controlled
combustion experiment.

## Limitations

The existing extractor is pattern-based and processes prose passages. It does
not parse arbitrary PSI data files or perform validated table extraction from
PDF/HTML. Figures, table headers, units split across columns, scanned pages,
multiple test conditions, and statements about intended rather than completed
tests can all defeat or mis-scope extraction. No extraction result is a
scientific review. Unstated and ambiguous values must remain null/unknown.
