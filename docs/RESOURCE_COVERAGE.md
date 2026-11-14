# NASA challenge resource coverage

This report describes repository artifacts, not a claim that all source content
or experimental data have been ingested. `data/official_resource_report.json`
is regenerated from current acquisition sidecars and indexed chunks.

## Coverage snapshot

| Measure | Recorded value | Source / interpretation |
|---|---:|---|
| Supplied challenge resource URLs | 10 | The user-supplied inventory, R1–R10, documented in `OFFICIAL_RESOURCES.md`. |
| Official resource inventory entries | 10 | `data/official_resources.json`; inventory IDs do not imply acquisition. |
| R1 related PSI catalog chunks surfaced in the live resource report | 12 | Existing named snapshots for PSI-25, PSI-69 and PSI-98, mapped as catalog context. They were not newly acquired by this task and are not dataset records. |
| Existing core NTRS documents ingested | 12 | `data/processed/manifest.json`; these are not the same as the ten challenge resource list. |
| Existing core passages | 294 | `data/processed/manifest.json`. |
| Raw experimental PSI data files recorded as downloaded | 0 | `raw_experimental_datasets_downloaded` in the core manifest. |
| Existing PSI named catalog records | 3 | PSI-25, PSI-69, PSI-98 version-pinned catalog snapshots in `data/benchmark_sources.json`. |
| Existing PSI file-listing snapshots | 1 | PSI-98 only; `psi-98-files.bin` is a JSON listing, not acquired dataset bytes. |
| Official resource IDs with acquired bytes or mapped catalog chunks | 10 | Live `acquired_resource_count` in `data/official_resource_report.json`; includes R1 PSI catalog context and guide, partial R3 page-only acquisition, and R2/R4–R10 content. |
| Official resource IDs with indexed chunks | 9 | Live `indexed_resource_count`; R3 watch page has no caption/transcript chunks. |
| Extracted experimental records from R1–R10 | 0 | `data/official_resource_report.json`; no dataset records have been extracted. |
| Non-null condition fields in mapped R1 catalog chunks | 0 | `data/official_resource_report.json`; null here means no catalog chunk condition values, not a completeness percentage. |

The live resource report maps the three existing PSI catalog snapshots to R1
for visibility and counts their 12 located source-description chunks. A NASA
PSI database guide is also stored under `data/raw/official/R1/`; it is not a
dataset. R2, R4–R10 source pages were fetched and indexed, and the R4 guide PDF
was fetched and indexed at physical page granularity. R3's official watch page
was fetched, but the advertised English caption endpoint returned an empty
body, so no transcript was created or indexed. This is catalog and background
content acquisition, not raw experimental data ingestion. The named benchmark
manifest records eight supplemental source snapshots, including the three PSI
catalog records, but they are separate from the core 12-document manifest. Existing condition drafts comprise 239
machine-extracted records across five investigations; none are established by
that count as R1–R10 reviewed metadata.

## Access and processing blockers

- PSI search and versioned catalog/file-listing responses exist in the current
  implementation, but bulk/individual scientific data file acquisition and
  per-file rights review are not recorded here. PSI catalog-level license
  metadata is not a blanket file-level grant.
- PSI raw dataset acquisition has not been performed; only catalog snapshots,
  one file listing, and the NASA PSI guide are present.
- R3 has a stored official watch page but no caption or timestamped transcript.
  No speech has been transcribed by inference.
- NASA Spinoff R8–R10 are indexed with `review_required` rights status and stay
  excluded from retrieval until rights review.
- The current generic article extractor excludes tables, captions and media;
  current PDF extraction is text-oriented and does not validate table values.
- No new-resource duplicate analysis or R1–R10 indexing statistics are
  available in the baseline manifests.

## Denominator and provenance policy

The resource denominator is the ten supplied URLs. An item counts as acquired
only when original bytes or a documented official transcript are present with
retrieval provenance. It counts as processed only when content extraction has
completed with retained source locators. A catalog JSON or file listing does
not count as a downloaded experimental data file. A metadata value counts as
validated only after a real human or authoritative validation event is
recorded. No such review is implied by software extraction.

This baseline report should be updated from machine-readable ingestion results
after any new acquisitions. Report denominators with every percentage and keep
missing, ambiguous, and not-stated fields separate from extraction errors.
