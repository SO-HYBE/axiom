# AXIOM — submission description

**Challenge:** *Flame in Freefall* (NASA Space Apps Challenge 2026)

**One sentence:** AXIOM is an evidence-grounded research dashboard that compares
a hypothetical spacecraft fire scenario with conditions actually documented in
NASA microgravity combustion literature, shows exactly where the evidence does
and does not apply, and turns documentation gaps into explicitly unexecuted
experiment proposals.

## What the project does

1. **Summarises with provenance.** 294 passages from 12 NASA documents are
   indexed with source, chunk, page locator and hash. Every surfaced claim is
   tied to a located passage or is withheld.
2. **Ranks transparently.** Retrieval is deterministic and explainable. No
   calibrated probability or arbitrary relevance score is presented as truth.
3. **Interprets conditionally.** The Mission Scenario Stress Test compares a
   user scenario with documented test conditions and classifies every parameter
   as exact match, partial match, mismatch or unknown.
4. **States absence honestly.** Unknown never becomes a match, and missing
   documentation is never presented as proof that an experiment was never
   conducted.
5. **Plans the next experiment.** The Next Experiment Planner derives
   documentation gaps and produces one to three traceable research proposals,
   each labelled `PROPOSED — NOT EXECUTED`.

## What makes it different

- **The unit of output is a located passage, not a paragraph.** Citations carry
  document, chunk and page identifiers, and every quote is checked as a literal
  substring of the cited passage.
- **The Safety Critic is deterministic.** It withholds unsupported numbers,
  strong safety claims and absence-treated-as-negative-result wording without
  asking a model whether a claim is acceptable.
- **Coverage is two numbers, not one score.** Documented coverage and alignment
  coverage answer different questions and are never blended into a confidence
  percentage.
- **The planner cannot invent a study.** It reuses user scenario values, labels
  them `user_scenario_value_not_measured`, cites its motivation and defers
  ranges, replication and safety controls to expert review.
- **The demonstration needs no key and no network.** The scenario workflow is
  fully local and deterministic.

## NASA data used

Twelve ingested NTRS documents covering **BASS-II**, **FLEX** and **SAFFIRE**
(including Saffire V modelling), plus a BASS-II ground-comparison paper. Three
PSI catalogue records and four NASA web/factsheet items support the evaluation
set. Three NTRS records are rights-restricted and are not ingested.

Full attribution, URLs and rights determinations:
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Technology

Python 3.12 standard library HTTP service, hand-written HTML/CSS/JavaScript
dashboard, JSON Lines corpus with SHA-256 integrity checks, atomic JSON
scenario persistence, optional Groq/OpenRouter/Ollama models, `pypdf` for
ingestion, Docker and Compose for deployment.

## How to run

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse -e .
# Linux / macOS
.venv/bin/python -m pip install --no-index --find-links wheelhouse -e .
python -m axiom serve --port 8767
```

Open `http://127.0.0.1:8767`, choose **Mission scenario**, load the **Crew
cabin · fabric sample** preset, then change oxygen, pressure or airflow.
The end-to-end script is in
[docs/DEMONSTRATION_GUIDE.md](docs/DEMONSTRATION_GUIDE.md).

## Verification

- `python -m unittest discover -s tests` reproduces the suite from a fresh
  clone.
- `node --test tests/js/dashboard_models.cjs` covers the dashboard model logic.
- `GET /healthz` verifies corpus readiness.
- Phase 8 of the validation record documents the current run.

Exact counts and skip reasons are in [docs/VALIDATION.md](docs/VALIDATION.md).
No accuracy, adoption or safety certification is claimed.

## Disclosures

- Solo participant. AI coding agents assisted implementation, source research,
  evaluation design and review. No human scientific review has been recorded.
- The project has a pre-event development history. Actual dates and lineage are
  preserved in [PROJECT_WORK.md](PROJECT_WORK.md); they are not backdated.
- Competition reuse authorization and the local organizing committee's exact
  work-window ruling remain unresolved. This submission does not assert
  eligibility. See
  [docs/RULES_AND_ELIGIBILITY.md](docs/RULES_AND_ELIGIBILITY.md).
- Code is MIT-licensed. NASA documents and third-party materials remain under
  their own terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Limitations in one paragraph

Condition metadata is machine-extracted and not human-reviewed; the corpus is
12 documents, not the NASA archive; matching is exact or range-based and is not
experimental equivalence; the Safety Critic reduces unsupported text but does
not establish truth; the saved evaluation run has zero independent scientific
grades; no fire-risk score or safety certification is produced; and every
proposed experiment requires qualified scientific and facility-safety review.
