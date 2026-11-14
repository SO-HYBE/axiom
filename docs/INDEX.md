# Documentation index

Start with the document that matches your task. Submission-facing documents are
current for this repository. Archived process records under
[`history/`](history/README.md) are preserved for provenance: they describe work
as it stood on their own date and are not rewritten to match later state.

## For judges and new readers

| Document | Read it for |
|---|---|
| [../README.md](../README.md) | Product overview, scientific problem, installation, screenshots, limitations |
| [../SUBMISSION.md](../SUBMISSION.md) | One-page submission description and disclosures |
| [DEMONSTRATION_GUIDE.md](DEMONSTRATION_GUIDE.md) | Step-by-step Mission Scenario → Planner walkthrough |
| [SCIENTIFIC_METHODOLOGY.md](SCIENTIFIC_METHODOLOGY.md) | Exact classification, coverage, gap and proposal rules |
| [SAFETY_AND_LIMITATIONS.md](SAFETY_AND_LIMITATIONS.md) | Hard boundaries and what must not be inferred |
| [RESEARCH_MOTIVATION.md](RESEARCH_MOTIVATION.md) | AXIOM question and its relationship to unreliable observation channels |
| [CHALLENGE_NOTES.md](CHALLENGE_NOTES.md) | Mapping of challenge outputs to implemented features |

## Data and provenance

| Document | Read it for |
|---|---|
| [DATA_SOURCES.md](DATA_SOURCES.md) | Each ingested and inventory-only NASA source, rights, URL, extraction limits |
| [DATA_PROVENANCE.md](DATA_PROVENANCE.md) | Capture dates, hashes and acquisition records for the shipped bytes |
| [OFFICIAL_RESOURCES.md](OFFICIAL_RESOURCES.md) | Official challenge resource inventory and processing status |
| [RESOURCE_COVERAGE.md](RESOURCE_COVERAGE.md) | Which official resources are acquired, indexed or catalog-only |
| [PSI_INGESTION.md](PSI_INGESTION.md) | NASA PSI catalog handling and its distinction from raw measurements |
| [METADATA_EXTRACTION.md](METADATA_EXTRACTION.md) | Condition-metadata extraction rules and review status |
| [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) | Licence layering for code, NASA documents, PSI records and dependencies |
| [RULES_AND_ELIGIBILITY.md](RULES_AND_ELIGIBILITY.md) | Dated challenge-rule research and unresolved eligibility questions |
| [../PROJECT_WORK.md](../PROJECT_WORK.md) | Actual creation dates, AI-assistance record and development provenance |
| [DEVELOPMENT_HISTORY.md](DEVELOPMENT_HISTORY.md) | Short history of the build phases |

## Engineering

| Document | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Runtime topology, module map, data model, request lifecycle |
| [API_REFERENCE.md](API_REFERENCE.md) | HTTP endpoints, request shapes, limits and error behaviour |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Local and Docker startup, host allow-list, persistence, verified status |
| [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md) | Free-tier static-site + Python API split, exact commands, CORS, Porkbun DNS, limits |
| [MODEL_SETUP.md](MODEL_SETUP.md) | Optional provider configuration |
| [PROVIDER_RELIABILITY.md](PROVIDER_RELIABILITY.md) | Provider retry, cooldown and failure handling |

## Science features

| Document | Read it for |
|---|---|
| [MISSION_SCENARIO.md](MISSION_SCENARIO.md) | Design of the scenario comparison and planner |
| [EVALUATION.md](EVALUATION.md) | Benchmark design, scoring policy and grading status |
| [FORMAL_PROPERTIES.md](FORMAL_PROPERTIES.md) | P1–P8 semantics, finite-run verdicts and integrity boundary |
| [TRACE_MUTATIONS.md](TRACE_MUTATIONS.md) | Mutation operators, ablation and recorded measurements |
| [METADATA_VALIDATION.md](METADATA_VALIDATION.md) | Extraction sample, metrics and review outcome |
| [AXIOM_FINAL_REPORT.md](AXIOM_FINAL_REPORT.md) | AXIOM deliverables, measured limits, demo and review queue |
| [EVALUATION_DASHBOARD.md](EVALUATION_DASHBOARD.md) | Evaluation views and impact charts |
| [INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md) | Review protocol and pending scientific validation |

## Validation and release

| Document | Read it for |
|---|---|
| [VALIDATION.md](VALIDATION.md) | Dated test counts, skip reasons and verification evidence |
| [RELEASE_GUIDE.md](RELEASE_GUIDE.md) | Offline release packaging and integrity checks |

## Archived process records

[`history/`](history/README.md) holds dated phase status reports, refinement and
roadmap notes, and the early technical specification and data inventory. They
are kept for provenance only. When an archived record conflicts with the current
documents above, the current documents win.
