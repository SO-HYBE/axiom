# API reference

The dashboard can be served by the same process as the JSON API, or from a
separately hosted static copy that calls the API cross-origin. Endpoints require
no authentication and return `application/json` unless noted. There is no upload
endpoint.

## Request and security rules

Every request is subject to:

- **Host allow-list.** Loopback host names for the listening port are always
  accepted. Any other `Host` must be declared with `AXIOM_ALLOWED_HOSTS` or
  `--allowed-host`. Undeclared hosts receive `403`.
- **Origin check.** A `POST` with an `Origin` header whose host differs from the
  request `Host` receives `403` unless that exact origin is listed in
  `AXIOM_ALLOWED_ORIGINS` or `--allowed-origin`. Declared origins also receive
  CORS response headers and `OPTIONS` preflight support for the JSON `POST`
  paths. Undeclared origins receive no CORS grant.
- **Content type.** `POST` bodies must be `application/json`; otherwise `415`.
- **Body limit.** A `POST` body must be between 1 byte and 100,000 bytes;
  otherwise `400`.
- **Shape.** The body must be a JSON object, not an array or scalar.
- **No-store.** Responses are sent with `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer` and a restrictive Content-Security-Policy.

Error bodies have the shape `{"error": "<message>"}`. Messages never contain a
local filesystem path.

## GET endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | Single-page dashboard (`text/html`) |
| `GET /config.js` | Dashboard runtime configuration (`window.AXIOM_API_BASE`; empty means same origin) |
| `GET /healthz` | Readiness probe; `200` when the corpus and inventory load, `503` otherwise |
| `GET /api/status` | Corpus counts, source inventory and workspace mode |
| `GET /api/conditions` | Extracted condition coverage, validation and review state |
| `GET /api/scenario-metadata` | Scenario fields, units, documented values, presets, corpus statistics |
| `GET /api/scenarios` | Paginated saved assessments |
| `GET /api/scenarios/{id}` | One saved assessment |
| `GET /api/demos` | Saved demonstration cards |
| `GET /api/demos/{id}` | A verified replay of one saved demonstration |
| `GET /api/benchmark` | Benchmark source audit and latest saved run summary |
| `GET /api/benchmark/{run}/answers` | Saved answers for a run |
| `GET /api/benchmark/{run}/impact` | Integrity-checked engineering impact summary |
| `GET /api/axiom/evaluation` | Recorded AXIOM three-arm result, or `status: not_run` |
| `GET /api/axiom/trace-lab` | Recorded mutation metrics, or `status: not_run` |
| `GET /api/axiom/extraction-validation` | Recorded extraction metrics, or `status: not_run` |
| `GET /api/runs` | Paginated saved research runs |
| `GET /api/runs/{id}` | One saved research run |
| `GET /api/comparisons` | Paginated saved baseline/AXIOM pairs |
| `GET /api/comparisons/{id}` | One saved comparison |

Query parameters for the paginated endpoints (`/api/scenarios`, `/api/runs`,
`/api/comparisons`):

| Parameter | Default | Constraint |
|---|---|---|
| `limit` | 20 | 1–100 |
| `offset` | 0 | ≥ 0 |
| `q` | empty | ≤ 500 characters, case-insensitive substring |

Unknown parameters or repeated values are rejected with `400`. Record
identifiers must match the stored identifier format; path traversal, encoded
separators and nested paths are rejected.

### `GET /healthz`

```json
{
  "status": "ok",
  "service": "axiom",
  "chunks": 294,
  "ingested_sources": 12,
  "sources": 19
}
```

A failure returns `503` with `{"status": "error", "service": "axiom",
"error": "Scientific data is unavailable"}`. The endpoint does not reveal paths
or environment values.

### `GET /api/scenario-metadata`

```json
{
  "fields": [
    {"field": "gravity", "label": "gravity regime", "type": "text", "units": [],
     "documented_values": [...]}
  ],
  "interests": [{"value": "flame_spread", "label": "flame spread"}],
  "presets": [{"preset_id": "cabin-fabric", "synthetic": true, "scenario": {...}}],
  "corpus": {
    "documents": 12, "passages": 294, "condition_records": 239,
    "extraction": "deterministic_pattern_v1",
    "review_status": "machine_extracted_not_human_reviewed"
  },
  "notices": ["..."]
}
```

## POST endpoints

### `POST /api/axiom/trace-demo`

Return a deterministic original/mutated trace comparison in memory. This does
not write either trace or the measured aggregate files. Allowed presets are
`remove_validation`, `publish_before_verify`, and `corrupt_evidence_id`.

```json
{"preset":"remove_validation"}
```

The response includes both traces, both monitor reports, the mutation record and
a plain-language explanation. It is built from a saved benchmark run and fails
if the required event is not present.

### `POST /api/scenario-assess`

Assess a hypothetical scenario and optionally save it.

```json
{
  "scenario": {
    "gravity": "microgravity",
    "fuel": "sibal fabric",
    "oxygen_percent": {"value": 21, "unit": "%"},
    "pressure_kpa": {"value": 101.325, "unit": "kPa"},
    "flow_cm_s": {"value": 20, "unit": "cm/s"}
  },
  "interest": "flame_spread",
  "description": "Optional text, not used for matching",
  "save": true
}
```

Allowed keys: `scenario`, `interest`, `description`, `save`. Any other key is
rejected. Text fields take a string; numeric fields take
`{"value": <number>, "unit": "<unit>"}`. An unsupported unit is rejected.

Response (abridged):

```json
{
  "schema_version": "scenario-assessment-v2",
  "scenario_id": "…",
  "target": {"gravity": "microgravity", "oxygen_percent": 21.0, ...},
  "scenario_input": {"...": "the user's original units and text"},
  "investigations": [
    {"investigation_id": "BASS-II", "parameters": [
      {"field": "oxygen_percent", "classification": "exact_match",
       "reason": "...", "records": [{"source_id": "...", "chunk_id": "...",
       "locator": "PDF page 4", "quote": "..."}]}
    ]}
  ],
  "coverage": {
    "numerator": 12, "denominator": 25,
    "documented_percent": 48.0,
    "alignment_numerator": 7, "alignment_percent": 28.0,
    "status_counts": {"exact_match": 4, "partial_match": 3,
                      "mismatch": 5, "unknown": 13}
  },
  "gaps": [{"gap_id": "gap-combination", "kind": "combination_not_jointly_documented"}],
  "proposals": [{"label": "AXIOM PROPOSED — NOT EXECUTED OR VALIDATED NASA EXPERIMENT"}],
  "safety_critic": {"summary": {"withheld": 0, "qualified": 0, "supported": 0}},
  "saved_locally": true
}
```

The numbers above illustrate the shape only. Actual values depend on the corpus
and scenario.

### `POST /api/scenario-plan`

Return proposals and gaps from a saved assessment without a new retrieval or
generation step.

```json
{"scenario_id": "…", "gap_ids": ["gap-combination"]}
```

`gap_ids` is optional. Response includes `reused_assessment: true`, the target,
the selected gaps and proposals, and the label
`AXIOM PROPOSED RESEARCH CONCEPTS — NOT EXECUTED OR VALIDATED`.

### `POST /api/ask`

Ask a research question.

| Field | Type | Default | Notes |
|---|---|---|---|
| `question` | string | required | 1–4000 characters |
| `provider` | string | `extractive` | `groq`, `openrouter`, `ollama`, `extractive` |
| `model` | string or null | provider default | ≤ 100 characters |
| `system` | string | `ignis` | `ignis`, `baseline`, `rag_only` (`ignis` is the retained serialized key for AXIOM's claim-check workflow and saved comparison records) |
| `intent` | string | `research` | `research`, `applicability` |
| `target` | object | `{}` | Condition values for applicability checks |
| `experiments` | array or null | null | ≤ 30 strings, each ≤ 150 characters |
| `source_ids` | array or null | null | ≤ 30 strings, each ≤ 150 characters |
| `include_overviews` | boolean | false | Include overview passages |
| `fresh` | boolean | false | Bypass the response cache |

The extractive provider needs no key. Hosted providers require a key in `.env`
or the environment.

### `POST /api/compare`

Run a baseline and an AXIOM pass over the same frozen inputs. It accepts the
same fields as `/api/ask`, rejects `provider = extractive`, and returns a saved
comparison object. It does not declare a winner and does not produce a
scientific grade.

## Static assets

All CSS, JavaScript and SVG are inline in `src/axiom/web/index.html`. There are
no CDN requests, external fonts or other runtime asset endpoints.

## Versioning

The API is unversioned and intended to run with the dashboard from the same
commit. Corpus and response schemas carry their own `schema_version` fields.
