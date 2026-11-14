# NASA Space Apps Flame in Freefall resource inventory

This inventory covers the ten URLs supplied in the challenge implementation
brief. The list is distinct from the pre-existing AXIOM/NTRS inventory. Being
listed here does not mean a resource has been acquired, parsed, indexed, or
cleared for redistribution. Status statements below are based on the repository
artifacts presently checked in; `docs/RESOURCE_COVERAGE.md` gives the exact
coverage boundary.

## Resource list

| ID | Resource | Category | Present repository status | Interpretation boundary |
|---|---|---|---|---|
| R1 | [PSI Data Repository: Combustion Science](https://psi.nasa.gov/physci/repo/search?q=combustion) | Primary experimental data discovery | Three existing PSI catalog records map to 12 catalog chunks; PSI-98 has one file-listing snapshot. NASA PSI guide stored at `data/raw/official/R1/PSI_database_guide.pdf`. No experimental PSI dataset file is recorded as downloaded. | Catalog descriptions/file names and the guide are not measurements. Existing PSI snapshots predate this ingestion. Each dataset file needs its own access and rights review. |
| R2 | [NASA Combustion Science](https://www.nasa.gov/glenn/glenn-expertise-space-exploration/physical-sciences-program/combustion-science/) | Scientific background and research documentation | Page acquired with provenance and indexed in `data/processed/official_resources/r2.json`. | Background material is not a substitute for a source-reported experimental result. |
| R3 | [NASA ScienceCasts: The Power of Studying Combustion on the ISS](https://www.youtube.com/watch?v=W1oXykoz9zg) | Educational multimedia | Official watch page acquired. English caption track was advertised, but timed-text requests returned empty bodies; no transcript or caption chunks were made. | Educational narration is not primary experimental evidence. No transcript is inferred from the video URL. |
| R4 | [A Researcher's Guide to International Space Station Combustion Science](https://www.nasa.gov/missions/station/a-researcher's-guide-to-combustion-science/) | Scientific background and research documentation | Page and linked PDF acquired; page and PDF text indexed with PDF page locators. | Text extraction does not validate scientific measurements or tables. |
| R5 | [Apollo 1](https://sma.nasa.gov/sma-disciplines/accllp/apollo-1) | Historical safety incident | Page acquired with provenance and indexed. | Apollo 1 was a pre-launch ground-test fire; it is not an in-flight spacecraft fire or controlled microgravity experiment. |
| R6 | [Apollo 13](https://sma.nasa.gov/sma-disciplines/accllp/apollo-13) | Historical safety incident | Page acquired with provenance and indexed. | The oxygen-tank event is an incident, not a combustion experiment. |
| R7 | [25 Years Ago: Fire Aboard Space Station Mir](https://www.nasa.gov/history/25-years-ago-fire-aboard-space-station-mir/) | Historical safety incident | Page acquired with provenance and indexed. | Operational incident narrative must remain distinct from controlled experimental evidence. |
| R8 | [Fireman's Air Tanks](https://spinoff.nasa.gov/node/9582) | Technology transfer | Page acquired and indexed; passages are marked `review_required` for rights and excluded from retrieval. | A Spinoff description is contextual technology-transfer material, not a primary microgravity combustion dataset. |
| R9 | [Fire Detector](https://spinoff.nasa.gov/node/9407) | Technology transfer | Page acquired and indexed; passages are marked `review_required` for rights and excluded from retrieval. | A Spinoff description is contextual technology-transfer material, not a primary microgravity combustion dataset. |
| R10 | [New Technology for the Fire Attire](https://spinoff.nasa.gov/node/9918) | Technology transfer | Page acquired and indexed; passages are marked `review_required` for rights and excluded from retrieval. | A Spinoff description is contextual technology-transfer material, not a primary microgravity combustion dataset. |

## Existing related sources

The repository also contains a separate 12-document NTRS core corpus and eight
named benchmark source snapshots. They are described in
[`DATA_SOURCES.md`](DATA_SOURCES.md). Some concern combustion investigations
that also appear in PSI (including BASS-II, FLEX and SAFFIRE), but they are not
automatically counted as acquisition of R1 or any other challenge resource.
The existing PSI records are catalog snapshots, not underlying datasets.

## Rights and attribution

For R1, use PSI's persistent identifiers and cite the applicable investigation
DOI as requested on PSI pages. The checked-in named-source loader accepts only
the exact expected CC0 identifier for the three existing PSI record snapshots;
this does not establish that every file listed by an investigation has the same
rights status. NASA web/media reuse guidance and per-document NTRS rights
determinations are source-specific. No NASA or Space Apps endorsement is
implied. See the rights record in [`DATA_SOURCES.md`](DATA_SOURCES.md) and
[`RULES_AND_ELIGIBILITY.md`](RULES_AND_ELIGIBILITY.md).
