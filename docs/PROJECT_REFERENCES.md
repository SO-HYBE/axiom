# AXIOM project references and resources

This list records the external sources, data, and software used to build and
evaluate AXIOM. Source-specific acquisition status and rights are retained in
the linked project records. “Used” does not mean that a source's conclusions
were independently validated.

## NASA data and research sources

| Source | Link | How it was used | Attribution / rights |
|---|---|---|---|
| NASA Technical Reports Server (NTRS), 12-document core corpus | [Source-by-source NTRS bibliography](DATA_SOURCES.md#ingested-core-corpus-12-documents) | PDF text extraction and passage indexing for BASS-II, FLEX, SAFFIRE, and one ground-comparison study; cited passages support retrieval and scenario comparisons. | Each document has a source-specific `Public Use Permitted` or `Work of the US Gov. Public Use Permitted` determination recorded in the linked bibliography and `data/sources.json`. These statements are not blanket Creative Commons licences. Cite NASA/NTRS and the individual report; NASA does not endorse AXIOM. PDF bytes are not redistributed. |
| NASA Physical Sciences Informatics (PSI): BASS-II (PSI-25), FLEX (PSI-69), SAFFIRE-I (PSI-98) | [BASS-II](https://psi.nasa.gov/physci/repo/data/investigations/PSI-25), [FLEX](https://psi.nasa.gov/physci/repo/data/investigations/PSI-69), [SAFFIRE-I](https://psi.nasa.gov/physci/repo/data/investigations/PSI-98) | Version-pinned investigation catalogue snapshots used as source descriptions and benchmark context. PSI-98 also has a file-listing snapshot. No experimental dataset files were downloaded; catalogue text and file names are not measurements. | The three catalogue snapshots state CC0-1.0 in publisher JSON. This does not establish rights for each listed file. Cite each PSI record and its DOI as appropriate. |
| NASA PSI database guide | [NASA PSI Data Repository](https://psi.nasa.gov/physci/repo/search?q=combustion) | Consulted to understand PSI repository fields and access; retained with R1 resources. | NASA source; attribution retained. It is guidance, not experimental data. |
| NASA NTRS FLEX report 20150023456, *Detailed Results from the Flame Extinguishment Experiment (FLEX) March 2009 to December 2011* | [NTRS record](https://ntrs.nasa.gov/citations/20150023456) | Selected report text is included as a named benchmark source. Its large PDF was deferred from the core corpus; extracted text is not a validated measurement table. | Document-specific `Public Use Permitted`; cite NTRS. |
| NASA ISS Science Blog, “Cool Flames on the International Space Station: An Anatomy of Discovery” | [Original article](https://blogs.nasa.gov/ISS_Science_Blog/2013/11/25/cool-flames-on-the-international-space-station-an-anatomy-of-discovery/) | Selected article prose provides explanatory FLEX context in the benchmark corpus. | NASA factual prose with attribution under the NASA media-use guidance recorded in the source manifest; no media reused and no endorsement implied. |
| NASA Science, “Research and Technology Development for Space (RTDFS)” | [NASA Science article](https://science.nasa.gov/biological-physical/investigations/rtdfs/) | Selected article prose provides contextual background in the benchmark corpus. | NASA factual prose with attribution under the NASA media-use guidance recorded in the source manifest; no document-specific CC licence identified. |
| NASA, *Spacecraft Fire Safety Demonstration (Saffire)* factsheet | [Factsheet PDF](https://www.nasa.gov/wp-content/uploads/2025/07/spacecraft-fire-safety-demonstration-saffire.pdf) | Selected factual text provides SAFFIRE background in the benchmark corpus. | NASA factual prose with attribution under NASA media-use guidance; no document-specific CC licence identified. |
| NASA Glenn, “Flame Burns Out on NASA’s Long-Running Spacecraft Fire Experiment” | [NASA Glenn article](https://www.nasa.gov/centers-and-facilities/glenn/flame-burns-out-on-nasas-long-running-spacecraft-fire-experiment/) | Selected article prose provides SAFFIRE-VI context in the benchmark corpus. | NASA factual prose with attribution under NASA media-use guidance; no document-specific CC licence identified. |
| NASA Space Apps 2026 challenge resources R1–R10 | [Resource-by-resource inventory](OFFICIAL_RESOURCES.md) | The R1 PSI repository, R2 combustion-science page, R3 ScienceCasts watch page, R4 researcher’s guide, R5 Apollo 1, R6 Apollo 13, R7 Mir fire history, and R8–R10 NASA Spinoff pages were acquired/indexed as described in the inventory. The Spinoff passages remain excluded pending rights review. R3 yielded no transcript. | NASA resources are attributed in the inventory. R1 catalog licence is not a file-level licence; R8–R10 remain `review_required`. Media-use guidance and per-item NTRS rights apply. NASA does not endorse AXIOM. |
| NASA and 2026 Space Agency Partner directory | [Official 2026 Space Agency Partners page](https://www.spaceappschallenge.org/2026/space-agency-partners/) | Consulted to identify this year’s agency partners. No non-NASA partner dataset, code, text, or image is recorded as used in AXIOM. | Directory is cited for partner identification only, not as project data. |

The NASA sources above include multiple NASA resources used in the project,
including NTRS research documents and the official challenge resources. They
are the NASA resources relevant to the Global Award resource requirement. The
2026 Space Agency Partners page is included for completeness; it is not a
claim that partner-agency data were used.

Three NTRS records were retained as inventory references only and not
downloaded or used in the corpus: [BASS-II Summary Report (20210011385)](https://ntrs.nasa.gov/citations/20210011385), [Preliminary Results from the Saffire VI Experiment (20240002981)](https://ntrs.nasa.gov/citations/20240002981), and [Fire Safety Implications of Preliminary Results from Saffire IV and V (20210017780)](https://ntrs.nasa.gov/citations/20210017780). Their stored rights status requires review; no report text is redistributed.

For the individual titles, dates, locators, acquisition details, and status of
all 12 NTRS core sources and eight named benchmark sources, see
[`DATA_SOURCES.md`](DATA_SOURCES.md). The 10 challenge-resource URLs, coverage,
and rights boundaries are listed in [`OFFICIAL_RESOURCES.md`](OFFICIAL_RESOURCES.md)
and [`RESOURCE_COVERAGE.md`](RESOURCE_COVERAGE.md).

## Software, services, and generated records

| Tool or material | Link | How it was used | Attribution / licence |
|---|---|---|---|
| Python 3.12+ | [Python](https://www.python.org/) | Runtime and standard-library HTTP service, retrieval, evaluation, and dashboard backend. | Python Software Foundation License. |
| pypdf 6.13.0 | [PyPI project](https://pypi.org/project/pypdf/) | Extracts text from source PDFs during ingestion; it does not OCR image-only pages. | BSD-3-Clause. |
| setuptools 80.9.0 | [PyPI project](https://pypi.org/project/setuptools/) | Build backend and editable installation support. | MIT. |
| Docker and Docker Compose | [Docker](https://www.docker.com/) | Optional container packaging and local deployment. | Third-party tools; no Docker code or imagery is redistributed. |
| Groq hosted inference; `qwen/qwen3.8-27b` | [Groq](https://groq.com/), [Qwen](https://qwenlm.github.io/) | Optional hosted model produced preserved, ungraded development benchmark answers. These are recorded as observed model output, not scientific findings or human review. | Provider and model terms apply to service/output; no claim of endorsement or scientific validation. Run records preserve model identifier and provenance. |
| AXIOM software, tests, dashboard, documentation, and original inline graphics | [Project repository](../README.md) | Original project implementation, evaluation tools, and UI. | MIT; see [`../LICENSE`](../LICENSE). Dashboard graphics are original CSS and inline SVG. No external images, icon packs, web fonts, or CDN scripts are used. |

Full dependency and rights notes are in [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).
No external image assets were used. Screenshots in `screenshots/` are captures
of the project dashboard, not third-party images. AI coding assistance is
disclosed in [`../SUBMISSION.md`](../SUBMISSION.md); no human scientific review
is claimed.
