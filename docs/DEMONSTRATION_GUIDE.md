# Demonstration guide

This guide reproduces the complete Mission Scenario → Next Experiment Planner
workflow from a fresh clone. It needs no API key, no network connection and no
model download. Every step uses the shipped corpus.

## Before you start

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse -e .
# Linux / macOS
.venv/bin/python -m pip install --no-index --find-links wheelhouse -e .
python -m axiom serve --port 8767
```

Open **http://127.0.0.1:8767**. If the page loads but `/healthz` returns an
error, the corpus files are missing; see [DEPLOYMENT.md](DEPLOYMENT.md).

Expected startup output:

```text
AXIOM research workspace: http://127.0.0.1:8767
Health check: /healthz
```

## 1. Open Mission scenario

In the left sidebar, select **Mission scenario**. The page title is
*How far does the evidence travel?*

You should see:

- a **Scenario builder** panel with ten parameters;
- three preset buttons above the fields;
- a corpus tag showing the number of documents and passages loaded;
- the note that a blank field means unknown.

The status line should stop saying *Loading corpus metadata* and show the loaded
corpus instead. If it shows an error, stop and check `data/processed/`.

## 2. Load the cabin preset

Select **Crew cabin · fabric sample**.

The form fills with:

| Parameter | Value |
|---|---|
| Gravity regime | Microgravity |
| Fuel or material | SIBAL fabric |
| Fuel geometry | Fabric sheet |
| Oxygen concentration | 21 % |
| Pressure | 101.325 kPa |
| Airflow speed | 20 cm/s |
| Fire behaviour of interest | Flame spread |

The preset is a **synthetic demonstration scenario**, not a mission
specification. The interface says so.

## 3. Inspect the evidence matrix

Press **Assess scenario** if the assessment has not already run.

Expected content:

1. **Summary cards** with documented coverage and alignment coverage as two
   separate percentages, plus the number of investigations compared.
2. **A parameter comparison matrix** with one row per investigation and one
   cell per specified parameter. Each cell is one of:
   - **Exact match** — a reported value equals the scenario value after unit
     conversion;
   - **Partial match** — the value lies inside a reported test range;
   - **Mismatch** — documented values differ;
   - **Unknown** — the corpus does not document a qualified value.
3. **Quoted evidence** under each cell: the sentence, source identifier, chunk
   identifier and page locator.

Check one thing by hand: a cell marked **Unknown** must show no evidence and must
not be described as proof that NASA never tested the condition.

The matrix is expected to contain a mixture of classifications. It will not be
uniformly green: the corpus documents BASS-II, FLEX and SAFFIRE conditions, and
a cabin fabric scenario does not align exactly with all of them.

## 4. Modify oxygen, airflow or pressure

Change **Oxygen concentration** from `21` to `30`, or **Airflow speed** from `20`
to `5`, or **Pressure** from `101.325` to `50`.

After the first assessment, editing a parameter re-runs the comparison
automatically. Observe:

- the summary percentages change;
- cells switch between exact, partial, mismatch and unknown;
- a **change-diff banner** appears above the results describing what changed;
- the evidence matrix re-renders with new quoted passages.

Nothing is sent to a model. The request is a local `POST /api/scenario-assess`.

## 5. Explore the evidence gaps

Scroll to the **Evidence gaps** section. Each gap states:

- what is missing;
- why it matters for the selected fire behaviour;
- what cannot be established;
- the documentation status (absent, combination-not-joint, contextual only,
  outside the scenario condition, range-only, planned-only, unqualified);
- which investigations contributed;
- the plausible explanations, always including that the condition may exist
  outside this corpus.

Look for **No single investigation documents the full combination**. This is the
gap the planner uses for its joint-condition proposal.

## 6. Open the Next Experiment Planner

Below the gaps, the **Next experiment proposals** section shows one to three
proposals. Each is headed by the badge *Proposed — not executed or validated*
and carries the label
`AXIOM PROPOSED — NOT EXECUTED OR VALIDATED NASA EXPERIMENT`.

Inspect one proposal and confirm it contains:

- a research question ending in `?`;
- a hypothesis prefixed *Hypothesis (proposed, not observed)*, stating that
  direction and magnitude are unknown;
- independent, controlled and dependent variables;
- an experimental design sketch that defers exact values, replication and
  safety controls to expert review;
- expected contribution, which does not claim safety;
- source-linked scientific motivation with quoted passages;
- proposed values marked `user_scenario_value_not_measured`;
- unresolved limitations.

Priority is shown as criteria, not as a score: gap kind, scenario relevance and
evidence traceability.

## 7. Export and reopen

1. Press **Export JSON**. A file named `axiom-scenario-<id>.json` downloads. It
   contains the scenario, target, classification matrix, coverage, gaps,
   critic checks and proposals.
2. Tick **Save this assessment locally** and assess again. The assessment
   appears under **Saved scenario assessments**.
3. Reload the page. The saved assessment is still listed and reopens with the
   same classifications and proposals.
4. Restart the server. The saved assessment is still there, because it is
   stored as a JSON file under `runs/scenarios/`.

This is the persistence boundary: saved assessments survive a restart only if
`runs/scenarios/` is on storage that survives. In Docker, that is the
`axiom-scenarios` volume.

## 8. Optional: the research workspace

Select **Research** and press the example question *What is SIBAL fabric made
of?*. With no API key the default provider is extractive, so AXIOM returns
ranked source passages rather than a generated answer. Select **Saved
demonstrations** to replay three recorded cases with no model call.

## 9. What to look for during review

| Check | Expected behaviour |
|---|---|
| Blank field | Displayed as unknown; never matched |
| Unknown cell | No evidence, explicit "not documented in this corpus" wording |
| Unit change | `200 mm/s` and `20 cm/s` produce the same comparison |
| Repeated assessment | Same corpus + same scenario = same classifications |
| Export | Downloadable JSON with the full assessment |
| Restart | Saved scenario reopens unchanged |
| Narrow screen | Matrix scrolls inside its panel; navigation remains usable |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| *Scientific corpus is missing* on startup | `data/processed/chunks.jsonl` absent | Restore the file from the repository or run `python -m axiom ingest` |
| `/healthz` returns 503 | Corpus or inventory unreadable | Check both `data/processed/chunks.jsonl` and `data/sources.json` |
| Saved scenarios disappear after `docker compose down` | Volume removed with `-v` | Use `docker compose stop`, or back up the `axiom-scenarios` volume |
| Live answer fails with a provider error | No key, quota or network | Use the extractive provider; the scenario workflow never needs a key |
