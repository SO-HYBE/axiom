# NASA data sources, rights and extraction record

This document records every external scientific source known to AXIOM, what was
actually ingested, how derived text was produced, and what cannot be concluded
from it. It is a data-provenance record, not a legal opinion.

Checked against `data/sources.json`, `data/processed/manifest.json` and
`data/benchmark_sources.json` in this repository. Counts below were read from
those files, not estimated.

## Summary

| Category | Count | Redistributed in this repository |
|---|---|---|
| NTRS documents ingested into the core corpus | 12 | Processed passages and metadata only; no PDF bytes |
| NTRS / PSI records kept as inventory references | 7 | Metadata and URLs only |
| Named benchmark sources (abstracts, articles, factsheet, PSI records) | 8 | Extracted passages plus source URLs; raw captures are `.bin` files with provenance sidecars |
| Total inventory entries | 19 | — |

Core corpus: **294 passages**, all carrying `source_id`, `chunk_id`, a page or
section locator, the passage text and a SHA-256 digest. The manifest records
`corpus_sha256` and `sources_inventory_sha256`.

Condition metadata: **239 machine-extracted records** across five investigation
groups. These records are marked `machine_extracted_not_human_reviewed`.

## Rights position

- The 12 ingested documents carry a document-specific NTRS statement of
  `Public Use Permitted` (two SAFFIRE items say `Work of the US Gov. Public Use
  Permitted`). That is a per-document determination, not a Creative Commons
  licence and not a blanket public-domain claim.
- Three NTRS records are `review_required` and were **not downloaded**:
  `ntrs-20210011385`, `ntrs-20240002981`, `ntrs-20210017780`. Their titles and
  URLs are retained for completeness only.
- The three PSI catalogue records state `CC0-1.0` in the version-pinned
  publisher JSON. They are used as catalogue references and named-source
  records, not as experimental measurement tables.
- NASA web articles and the Saffire factsheet are used under NASA media-use
  guidance with attribution. No endorsement is implied.
- Raw PDF bytes of the 12 core documents are deliberately excluded from this
  repository. `python -m axiom ingest` re-acquires them from NTRS.
- No third-party copyrighted publication is redistributed merely because it was
  publicly accessible.

See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for the licence layering.

## Ingested core corpus (12 documents)

Each row below was ingested. "Extraction" is deterministic PDF text extraction
followed by passage segmentation; no language model writes corpus text.

### BASS-II and ground comparison

| Field | Value |
|---|---|
| Investigation | BASS-II (Burning and Suppression of Solids-II) |
| Publication | *Combustion of Solids in Microgravity: Results from the BASS-II Experiment* |
| Identifier | NTRS 20160000593 |
| URL | https://ntrs.nasa.gov/citations/20160000593 |
| Date | 2014-10-23 |
| Type | Research presentation |
| Rights | Public Use Permitted |
| Metadata | Experiment label, publication date and source type from the NTRS record |
| Limitations | Presentation format; multiple test conditions in one document; no single condition is inferred for the whole document |

| Field | Value |
|---|---|
| Investigation | BASS-II |
| Publication | *Microgravity Flammability of PMMA Rods in Concurrent Flow* |
| Identifier | NTRS 20150008961 |
| URL | https://ntrs.nasa.gov/citations/20150008961 |
| Date | 2015-05-17 |
| Type | Conference paper |
| Rights | Public Use Permitted |
| Limitations | PMMA rod geometry; results do not generalise to fabric or thick fuels |

| Field | Value |
|---|---|
| Investigation | BASS / BASS-II |
| Publication | *Concurrent Flame Growth, Spread and Extinction over Composite Fabric Samples in Low Speed Purely Forced Flow in Microgravity* |
| Identifier | NTRS 20150008962 |
| URL | https://ntrs.nasa.gov/citations/20150008962 |
| Date | 2015-05-17 |
| Type | Conference paper |
| Rights | Public Use Permitted |
| Limitations | Fabric samples and low-speed forced flow only; extraction may miss values stated only inside figures |

| Field | Value |
|---|---|
| Investigation | BASS-II / ground comparison |
| Publication | *Correlation of Normal Gravity Mixed Convection Blowoff Limits with Microgravity Forced Flow Blowoff Limits* |
| Identifier | NTRS 20160012691 |
| URL | https://ntrs.nasa.gov/citations/20160012691 |
| Date | 2016-05-15 |
| Type | Conference paper |
| Rights | Public Use Permitted |
| Limitations | Ground-comparison regime; must not be read as a microgravity result |

### FLEX (Flame Extinguishment Experiment)

| Field | Value |
|---|---|
| Investigation | FLEX |
| Publication | *Multi-User Droplet Combustion Apparatus - Flame Extinguishment Experiment* |
| Identifier | NTRS 20090014812 |
| URL | https://ntrs.nasa.gov/citations/20090014812 |
| Date | 2009-02-23 |
| Type | Experiment overview |
| Rights | Public Use Permitted |
| Limitations | Overview document; planned capabilities and reported results are retained as distinct evidence statuses |

| Field | Value |
|---|---|
| Investigation | FLEX |
| Publication | *FLEX: A Decisive Step Forward in NASA's Combustion Research Program* |
| Identifier | NTRS 20120015928 |
| URL | https://ntrs.nasa.gov/citations/20120015928 |
| Date | 2012-06-26 |
| Type | Programme overview |
| Rights | Public Use Permitted |
| Limitations | Programme narrative; not a test-condition table |

| Field | Value |
|---|---|
| Investigation | FLEX |
| Publication | *Dynamics of Water Absorption and Evaporation During Methanol Droplet Combustion in Microgravity* |
| Identifier | NTRS 20130010979 |
| URL | https://ntrs.nasa.gov/citations/20130010979 |
| Date | 2012-11-28 |
| Type | Conference paper |
| Rights | Public Use Permitted |
| Limitations | Methanol/water droplets; not a solid-fuel result |

| Field | Value |
|---|---|
| Investigation | FLEX |
| Publication | *Isolated Single Droplet Combustion: FLEX Experiments onboard the International Space Station* |
| Identifier | NTRS 20210022617 |
| URL | https://ntrs.nasa.gov/citations/20210022617 |
| Date | Not stated in the stored metadata |
| Type | Research report |
| Rights | Public Use Permitted |
| Limitations | Publication date is null in the inventory; it is not guessed |

### SAFFIRE (Spacecraft Fire Experiment)

| Field | Value |
|---|---|
| Investigation | SAFFIRE |
| Publication | *The Spacecraft Fire Experiment (Saffire) - Objectives, Development and Status* |
| Identifier | NTRS 20170001636 |
| URL | https://ntrs.nasa.gov/citations/20170001636 |
| Date | 2016-05-18 |
| Type | Conference paper |
| Rights | Work of the US Gov. Public Use Permitted |
| Limitations | Objectives/status document; some statements describe plans, not completed tests |

| Field | Value |
|---|---|
| Investigation | SAFFIRE |
| Publication | *Results of Large-Scale Spacecraft Flammability Tests* |
| Identifier | NTRS 20170008805 |
| URL | https://ntrs.nasa.gov/citations/20170008805 |
| Date | 2017-07-16 |
| Type | Conference paper |
| Rights | Public Use Permitted |
| Limitations | Large-scale spacecraft configuration; scale-dependent transferability must not be assumed |

| Field | Value |
|---|---|
| Investigation | SAFFIRE |
| Publication | *Saffire: A Novel Approach to Study of Spacecraft Fire Safety Using Un-Manned Spacecraft* |
| Identifier | NTRS 20180005168 |
| URL | https://ntrs.nasa.gov/citations/20180005168 |
| Date | 2017-10-25 |
| Type | Conference paper |
| Rights | Public Use Permitted |
| Limitations | Method/overview emphasis; condition extraction is sparse |

| Field | Value |
|---|---|
| Investigation | SAFFIRE-V |
| Publication | *Vehicle Modeling During the Burning of Thermally Thick Samples in the Saffire V Experiments* |
| Identifier | NTRS 20240008602 |
| URL | https://ntrs.nasa.gov/citations/20240008602 |
| Date | Not stated in the stored metadata |
| Type | Conference paper |
| Rights | Work of the US Gov. Public Use Permitted |
| Limitations | Modelling study; model inputs are not experimental measurements |

## Inventory-only records (not ingested)

These records are present so that the corpus boundary is explicit. Their text is
not part of any retrieval or comparison.

| Identifier | Investigation | Title | Status | Rights |
|---|---|---|---|---|
| `ntrs-20150023456` | FLEX | Detailed Results from the Flame Extinguishment Experiment (FLEX) March 2009 to December 2011 | Large file deferred; named-source text acquired separately | Public Use Permitted |
| `ntrs-20210011385` | BASS-II | Burning and Suppression of Solids-II (BASS-II) Summary Report | Not downloaded | Review required |
| `ntrs-20240002981` | SAFFIRE-VI | Preliminary Results from the Saffire VI Experiment | Not downloaded | Review required |
| `ntrs-20210017780` | SAFFIRE-IV/V | Fire Safety Implications of Preliminary Results from Saffire IV and V Experiments on Large Scale Spacecraft Fires | Not downloaded | Review required |

`ntrs-20150023456` contributes text through the named-source record below, not
through the core PDF corpus.

## Named benchmark sources (8)

These sources support the 36-question evaluation set. Derived passages live in
`data/processed/named_sources/`; raw captures live in `data/raw/named/` with a
`.provenance.json` sidecar recording URL, retrieval evidence, byte count and
SHA-256.

| Identifier | Experiment | Source | Rights basis |
|---|---|---|---|
| `psi-25` | BASS-II | PSI investigation record, https://psi.nasa.gov/physci/repo/data/investigations/PSI-25 | CC0-1.0 stated in publisher JSON |
| `psi-69` | FLEX | PSI investigation record, https://psi.nasa.gov/physci/repo/data/investigations/PSI-69 | CC0-1.0 stated in publisher JSON |
| `psi-98` | SAFFIRE-I | PSI investigation record, https://psi.nasa.gov/physci/repo/data/investigations/PSI-98 | CC0-1.0 stated in publisher JSON |
| `ntrs-20150023456` | FLEX | NTRS text and rights pages, https://ntrs.nasa.gov/citations/20150023456 | Document-specific Public Use Permitted |
| `named-flex-blog` | FLEX | NASA ISS Science Blog article (Internet Archive capture), https://blogs.nasa.gov/ISS_Science_Blog/2013/11/25/cool-flames-on-the-international-space-station-an-anatomy-of-discovery/ | NASA factual prose with attribution; no media reused |
| `named-rtdfs` | RTDFS | NASA science article, https://science.nasa.gov/biological-physical/investigations/rtdfs/ | NASA factual prose with attribution; selected prose only |
| `named-saffire-factsheet` | SAFFIRE | NASA Saffire factsheet PDF, https://www.nasa.gov/wp-content/uploads/2025/07/spacecraft-fire-safety-demonstration-saffire.pdf | NASA factual prose with attribution |
| `named-saffire-vi-news` | SAFFIRE-VI | NASA Glenn news article, https://www.nasa.gov/centers-and-facilities/glenn/flame-burns-out-on-nasas-long-running-spacecraft-fire-experiment/ | NASA factual prose with attribution; selected prose only |

## Extraction methodology

1. **Acquisition.** NTRS metadata and PDFs are fetched by `src/axiom/ingest.py`
   from the URLs recorded in `data/sources.json`, with the permission status
   checked first. Named sources are fetched by
   `src/axiom/benchmark_named_sources.py` and stored with provenance sidecars.
2. **Text extraction.** `pypdf` extracts page text. No OCR is applied, so
   scanned image-only pages produce no text.
3. **Segmentation.** Text is split into passages with page/section locators.
   Each passage receives a SHA-256 digest over its text.
4. **Condition extraction.** `src/axiom/experiment_metadata.py` applies explicit
   patterns to quoted sentences to find numeric and categorical test
   conditions. Each record stores its quote, locator, scope and evidence status
   (`reported_test_condition`, `proposed`, `background`, and so on). Only
   qualified reported test conditions are eligible for matching.
5. **Integrity.** `data/processed/manifest.json` records corpus and inventory
   hashes; `load_chunks` recomputes each passage digest on every load.

## Known extraction limitations

- Machine-extracted metadata is **not human-verified**.
- Values that appear only in figures, or in tables whose cells extract without
  their column headers, may be missed or mis-scoped.
- A sentence can describe a plan, a literature value or a limit rather than a
  test condition. AXIOM records an evidence status but cannot guarantee the
  classification.
- Numeric ranges are recorded as ranges. Their endpoints are not treated as
  individually tested values.
- The corpus is 12 documents. It is a documented subset, not a complete NASA
  archive, and it is not a transcription of an official challenge dataset list.
- Publication dates are `null` where the stored NTRS metadata did not state one;
  they are never filled with a plausible guess.

## How to re-acquire the excluded bytes

```bash
python -m axiom ingest            # core NTRS PDFs -> data/raw/*.pdf
python -m axiom benchmark-ingest  # named benchmark captures -> data/raw/named/
```

Both commands respect the `permission_status` recorded in the inventory.
