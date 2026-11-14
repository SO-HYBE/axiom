# Run and verify an AXIOM release

## Install from the release

Extract `ignis-release.zip` into its own directory. Use Python 3.12 or newer and
run `launch.ps1`, or double-click `launch.cmd` on Windows. The launcher changes
to its own directory, creates `.venv`, installs the packaged dependency wheels
and starts the loopback dashboard at `http://127.0.0.1:8767`.

The first launch installs the pinned dependencies. Later launches can use
`launch.ps1 -NoInstall`. Choose another port with `launch.ps1 -Port 8770`.
No model download is performed. Saved demos require no API key or inference.

For a manual offline installation from the extracted directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse -e .
.\.venv\Scripts\python.exe -m ignis serve --port 8767
```

Always run from this directory, or pass the global CLI option
`--root C:\path\to\extracted-release` before the subcommand. Source checkouts
exclude the local data caches and wheels; they need dependency installation and
NASA ingestion before research or frozen replay.

## Saved walkthrough

Open **Saved demos** in the sidebar:

1. **An answer with its source:** Q002, the saved FLEX source description. Open
   NASA sources and match the claim to its cited words. Model support is provisional.
2. **A conclusion held back:** Q008, a cabin-fire guarantee. Inspect the missing
   conditions and applicability checks that caused withholding.
3. **A source without the requested measurements:** Q022 requests confidence
   intervals using only an abstract. The complete abstract is supplied as requested
   context; the saved answer withholds the unavailable numbers. The interface
   does not claim lexical relevance or scientific validation.

Each case opens an actual frozen record and labels the result as a replay.
Historical provider calls remain in its audit; this click makes zero new calls.
The regular Research view can also run the Source preview provider offline.

The Evaluation view reports 108 scheduled jobs: 106 completed, 2 failed and
0 pending. All 36 named source scopes are available. Open saved answers to inspect
successful and failed attempts. Scientific metrics remain ungraded.

## Evaluation walkthrough

Open **Evaluation** to see 34 RAG claims become 21 released AXIOM claims across
34 completed matched cases. Select a withholding reason, open a question, and
compare the draft with the checked answer and original quotations. The outcomes
chart keeps both failed executions visible. Download results exports the derived
JSON. No API key or new inference is required. These are observed release
decisions; scientific improvement remains ungraded.
[Counting method and current validation](EVALUATION_DASHBOARD.md).

## Build and verify

```powershell
python -m pip download --only-binary=:all: --dest wheelhouse pypdf==6.13.0 setuptools==80.9.0
python -m axiom release-build --output dist/phase7
python -m axiom release-verify dist/phase7
```

The builder checks source inventories, text-cache hashes and path containment.
It writes `ignis-release.zip`, `release_manifest.json` and a SHA256 sidecar.
ZIP members have canonical paths, fixed archive timestamps and recorded hashes;
rebuilding unchanged inputs produces the same archive bytes. Verification checks
every member and rejects path traversal, duplicate or unexpected files, symlinks,
oversized members and tampering. This verifies local integrity, not authorship.

The package contains app source, tests, docs, pinned wheels, source inventories,
frozen text/metadata caches, three demo references, the evaluation report and the
four selected benchmark histories including failures and generation snapshots.
The 12 core PDFs remain accessible through primary URLs and recorded hashes;
their bytes are not bundled. Named HTML/JSON/PDF source snapshots needed for
offline section replay are included under the explicit admission policy.

API keys, `.env`, virtual environments, Git metadata, model-response caches and
the private reviewer mapping are excluded. No upload or publication occurs.
Each source retains its recorded reuse rights; no blanket license is inferred.

## Checks and limits

```powershell
python -m unittest discover -s tests -v
node --test tests/js/dashboard_models.cjs
python -m axiom demo
python -m axiom benchmark-inspect 3c3cc0f1e4b949a8a33296e94417f13c
```

The validation record documents the clean-environment check. Preserve the release
manifest alongside a distributed copy. Source changes create a new release;
never rewrite a frozen benchmark to make it match changed code or sources.

The latest source/critic changes and actual failed executions are documented in
[the safety follow-up](history/SAFETY_IMPROVEMENTS.md). Scientific labels remain unreviewed,
provider aliases are not immutable snapshots, eleven lexical misses are covered
only by explicitly requested context, and caches/retries confound timing.
Observed elapsed deadline overruns remain a stated limitation. Packaging does not
establish scientific correctness or hide these limits.
