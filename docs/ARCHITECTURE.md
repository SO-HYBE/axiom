# Architecture

AXIOM is a single Python process with a static dashboard. The architecture is
deliberately small: one install step, one process, one persistent directory, no
build toolchain and no database.

## Runtime topology

```text
┌─────────────────────────────────────────────────────────────────┐
│ Browser                                                         │
│  src/axiom/web/index.html  (HTML + CSS + JS + inline SVG)       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ same-origin fetch(), JSON
┌──────────────────────────▼──────────────────────────────────────┐
│ src/axiom/server.py  (ThreadingHTTPServer)                      │
│  • Host allow-list   • Origin check   • body limits             │
│  • GET /healthz      • static dashboard                         │
└───────┬─────────────────┬──────────────────┬────────────────────┘
        │                 │                  │
        ▼                 ▼                  ▼
  research / retrieval  scenario /        run_records
  critic / providers    transferability   (atomic JSON)
        │                 │                  │
        ▼                 ▼                  ▼
  data/processed/      data/processed/    runs/scenarios/
  chunks.jsonl         chunks.jsonl       *.json
```

## Module map

| Module | Responsibility |
|---|---|
| `cli.py` | Command-line entry points, including `serve` |
| `server.py` | HTTP routing, host/origin validation, health probe |
| `research.py` | Corpus loading, answer orchestration, condition records |
| `retrieval.py` | Deterministic evidence ranking and passage selection |
| `critic.py` | Deterministic claim checks and withholding rules |
| `providers.py` | Optional model transports, caching, retries and limits |
| `experiment_metadata.py` | Quoted condition extraction and investigation grouping |
| `transferability.py` | Unit normalisation, four-way classification, coverage, gaps, proposals, Safety Critic |
| `applicability.py` | Deterministic exact/range/category condition applicability with explicit unknowns and conflicts |
| `trace.py`, `monitor.py` | Versioned event records, observation-integrity checks, three-valued P1–P8 monitor |
| `mutations.py`, `mutation_lab.py`, `faults.py` | Deterministic seeded mutations, constructed fault corpus, ON/OFF ablation and metrics |
| `extraction_validation.py` | Fixed-sample source-quote review labels and extraction metrics |
| `axiom_evaluation.py`, `trace_demo.py` | Offline three-arm analysis, question bootstrap intervals and in-memory demo traces |
| `scenario.py` | Scenario validation, presets, assessment orchestration, planning |
| `run_records.py` | Atomic save/load/list for runs, comparisons and scenarios |
| `demo.py` | Verified replay of three saved demonstrations |
| `ingest.py` | Allowlisted NTRS acquisition and corpus build |
| `benchmark_*`, `evaluate.py`, `review*.py` | Optional evaluation and review tooling |
| `release.py` | Allowlisted, hashed offline packaging |

## Data model

### Corpus

`data/processed/chunks.jsonl`, one JSON object per line:

```json
{
  "chunk_id": "…",
  "source_id": "ntrs-20160000593",
  "text": "…",
  "locator": "PDF page 7",
  "sha256": "…"
}
```

`load_chunks` recomputes each digest and rejects a modified corpus.
`data/processed/manifest.json` binds the corpus hash and the inventory hash.

### Inventory

`data/sources.json` lists 19 records with identifiers, URLs, experiment labels,
publication dates, licence statements, permission status, comparability notes
and limitations. It is the single source of truth for rights decisions.

### Condition records

Built at request time from the corpus by `experiment_metadata.py`. Each record
keeps its quote, locator, evidence status, scope and extraction rule. Records are
not persisted into the corpus, so extraction improvements apply immediately.

### Saved scenarios

`runs/scenarios/<scenario_id>.json` holds one complete assessment. Writes use a
temporary file followed by an atomic replace, under a write lock. Reads validate
the record shape and identifier before returning it.

## Request lifecycle: scenario assessment

1. The browser posts a scenario object to `/api/scenario-assess`.
2. The server validates Host, Origin, content type and body size.
3. `scenario._validated` rejects unknown keys and normalises units.
4. `load_chunks` reads and verifies the corpus.
5. `experiment_metadata.investigations` groups records into five investigation
   aliases.
6. `transferability.assess` classifies every scenario × investigation cell and
   computes both coverage numbers.
7. `identify_gaps` classifies documentation gaps; `propose` builds at most three
   labelled proposals.
8. `audit` runs the deterministic Safety Critic over generated statements.
9. If `save` is true, `run_records.save_scenario` writes the snapshot
   atomically.
10. The server serialises the result with `allow_nan=False`.

No step calls a model.

## AXIOM assurance path

The research/scenario workflow remains intact. Saved pipeline runs are projected
into `axiom-trace-v1` records by `trace.build_trace`; this initial integration is
post-hoc and does not change model behavior. `monitor.evaluate` classifies
observation integrity before evaluating P1–P8. The mutation lab compares each
mutated trace to its original reference with integrity ON and OFF. The browser
reads result files through fixed read-only `/api/axiom/{evaluation,trace-lab,
extraction-validation}` routes. A preset POST to `/api/axiom/trace-demo` returns
one original and mutated trace in memory and does not persist it. Missing files
return `status: not_run`; malformed or oversized files fail closed. See
[FORMAL_PROPERTIES.md](FORMAL_PROPERTIES.md).

## Persistence and deployment boundaries

- **Saved scenarios** live under `runs/scenarios/`. This is the only directory
  that must be writable at runtime.
- **Saved research runs and comparisons** live under `runs/`.
- **Frozen benchmark evidence** lives under `runs/benchmarks/` and is read-only
  in normal operation.
- **Model cache** lives under `runs/model_cache/` and is intentionally excluded
  from the release.
- The container image runs as an unprivileged user and mounts a named volume at
  `/app/runs/scenarios`.

## Determinism

- Corpus text and metadata are fixed by hashes.
- Classification uses explicit alias tables, closed unit tables and exact
  equality or range containment.
- Aggregations sort explicitly.
- The only random value is the UUID used as the scenario storage key.

## Why not a database or a SPA framework

The workload is a few hundred passages and a few dozen saved records per user.
JSON files with atomic replacement meet the durability requirement without an
operational dependency. The dashboard has no build step, so a judge can clone
the repository and run one command. If the corpus or concurrency grows, the
`run_records` boundary is the natural place to introduce SQLite.

## Failure behaviour

| Failure | Behaviour |
|---|---|
| Corpus missing or modified | Startup refused; `/healthz` returns 503 |
| Inventory unreadable | `/healthz` returns 503; endpoints return 503 |
| Scenario invalid | `400` with a specific message |
| Save fails | Assessment is still returned with `saved_locally: false` and a save error |
| Provider missing key | `400` with a configuration message; extractive mode still works |
| Provider timeout or quota | Recorded per request; no fabricated answer |
| Unknown host or cross-origin POST | `403` before any work |
