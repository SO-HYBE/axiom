# PSI discovery and ingestion

## What was inspected

The repository's existing PSI integration is in
`src/axiom/benchmark_named_sources.py`. It retrieves version-pinned PSI
investigation JSON from the `geode-py/ws/repo/investigations/{accession}/{version}`
endpoint. For PSI-98 it additionally posts a study/version request to
`geode-py/ws/files/v2` to obtain the publisher's file-listing JSON. The loader
checks response identity, version, public/restricted flags, DOI, and the
publisher-provided `CC0-1.0` identifier for PSI-25, PSI-69 and PSI-98. It
preserves raw response bytes and provenance sidecars and derives located
catalog-description passages. The code explicitly treats file names as a
listing, not as experimental values.

The PSI public search page is a JavaScript-backed catalog. An observed indexed
search page exposed investigation identifiers and pagination (25 items per
page; 133 results in that observed response). This observation is not a
repository-wide count or a guarantee that the result set is stable. The
versioned investigation and file-listing endpoints are already used by the
application; this inspection did not establish that NASA publishes a supported
public API contract for them. The current implementation does not implement
search pagination or bulk download of PSI data files.

NASA's [PSI database guide](https://assets.science.nasa.gov/content/dam/science/bps/bps-general/bps-data_osdr_psi/Complete_PSI_Database_Guide.pdf)
documents keyword/Boolean search, research-area and project-type filters,
sorting, page sizes of 25/50/100, and downloads selected from investigation
file/folder controls. NASA's [public-access page](https://science.nasa.gov/biological-physical/data/osdr/data-repository-portal-login/)
says open data can be browsed/downloaded without a submission account. NASA's
[large-request process](https://science.nasa.gov/uncategorized/new-file-download-process-for-large-requestspsi-new-file-download-process/)
describes a separate email-link workflow for large downloads. These documented
UI facts do not establish an API or a blanket file license. NASA's
[repository terms](https://science.nasa.gov/reference/osdr-help-terms-and-conditions/)
require attention to contributor copyright notices and permissions.

## Current acquisition boundary

The existing named-source snapshots cover PSI-25 version 4 (BASS-II), PSI-69
version 5 (FLEX), and PSI-98 version 4 (SAFFIRE-I). The raw snapshots are
`data/raw/named/psi-25-record.bin`, `psi-69-record.bin`, `psi-98-record.bin`,
and `psi-98-files.bin`, each accompanied by a provenance sidecar. Their selected
derived passages are in `data/processed/named_sources/`. These files preserve
catalog metadata and, for PSI-98, a file listing. They do not contain downloaded
experimental data files. The core corpus manifest independently records
`raw_experimental_datasets_downloaded: 0`.

Other experimental data access facts, including the complete API contract,
authentication for any restricted items, pagination mechanics, bulk access,
file-level rights, and formats available across all relevant investigations,
remain unverified. No restricted resource is accessed. A catalog-level license
must not be assumed to grant rights for every linked asset. File-level access
and notices must be checked before downloading or redistributing any asset.

## Existing processing

For the three known investigation snapshots, the loader preserves selected
publisher fields such as objective, approach, DOI, license identifier, and a
recursive PSI-98 file listing. It emits source-description chunks with source
IDs, canonical investigation URLs, source kind, exact publisher-field
locators, and hashes. PSI catalog records are excluded from ordinary evidence
retrieval unless the caller explicitly requests verified source descriptions.
They contain no validated measurement-table ingestion.

The current code has bounded responses (2 MB), exact-URL redirect checks, and
per-file retrieval checks. It does not provide a PSI dataset downloader or
dataset parsers for CSV, XML, ZIP, video, or other investigation assets. The
generic HTML extractor is prose-oriented and intentionally excludes tables and
captions.

## Rights, citation, and limitations

PSI asks users to cite publicly available NASA-funded collections using the
persistent identifier/DOI listed on the investigation page. Existing checked-in
records carry publisher DOI and CC0 metadata as recorded in their per-source
rights fields. These observations apply only to those catalog records and do
not make a blanket determination for all file assets. Preserve DOI, accession,
version, original file name, download URL, acquisition time, and SHA-256 for
each future acquisition. Unknown metadata remains null.

No raw PSI dataset is currently available through this repository's core
corpus. The three PSI catalog snapshots are not proof that all relevant PSI
investigations have been found, that all PSI records are openly downloadable,
or that any source-reported condition has been scientifically validated.
