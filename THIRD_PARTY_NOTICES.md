# Third-party notices and licence layering

AXIOM is **not** distributed under a single blanket licence. Three layers of
material have different terms.

## 1. Original AXIOM software and documentation

Original source code, tests, dashboard markup and project documentation are
released under the **MIT License**. The full text is in [`LICENSE`](LICENSE).

Copyright (c) 2026 AXIOM project contributors.

This covers, for example, `src/axiom/**`, `tests/**`, `scripts/**`, the
dashboard HTML/CSS/JavaScript, and the original prose in `README.md`, `docs/`
and `SUBMISSION.md`. It does **not** cover NASA publications, NASA datasets,
third-party libraries or saved model output.

## 2. NASA publications and datasets

NASA documents and derived passages remain under the terms stated by NASA for
each item. They are **not** relicensed under MIT.

- Twelve NTRS documents are recorded as `Public Use Permitted` (two SAFFIRE
  items as `Work of the US Gov. Public Use Permitted`). The determination is
  per document and recorded in `data/sources.json`.
- NASA web articles and the Saffire factsheet are used under NASA media-use
  guidance with attribution. NASA does not endorse this project.
- Three PSI catalogue records state `CC0-1.0` in the version-pinned publisher
  JSON.
- Three NTRS records are marked `review_required`; they are referenced by title
  and URL only and are not ingested or redistributed.
- Raw PDF bytes of the core corpus are not redistributed. Processed passages
  retain their source URL, identifier and locator so the original can be
  consulted.
- NASA does not endorse, sponsor or certify AXIOM or any derived statement.

Source-by-source attribution is in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

### NASA attribution statement

> NASA material used in this repository was retrieved from the NASA Technical
> Reports Server (NTRS), NASA Science, NASA PSI and NASA web pages cited in
> `data/sources.json` and `docs/DATA_SOURCES.md`. NASA does not endorse this
> project. Original publication rights remain with their respective holders.

## 3. Third-party software

| Component | Version | Licence | Role |
|---|---|---|---|
| [pypdf](https://pypi.org/project/pypdf/) | 6.13.0 | BSD-3-Clause | PDF text extraction during corpus ingestion |
| [setuptools](https://pypi.org/project/setuptools/) | 80.9.0 | MIT | Build backend and editable installs |
| Python | 3.12+ | PSF License | Runtime |

Both Python packages are bundled as unmodified wheels in `wheelhouse/` so that
installation can be performed offline. Their licence texts are inside the wheel
metadata and at the upstream projects.

## Saved model output

`runs/benchmarks/` contains recorded answers produced during development by a
hosted model served through Groq (`qwen/qwen3.8-27b`). These records are
preserved as **observed system behaviour**, not as scientific findings, and not
as an endorsement by the model vendor or by NASA. They are ungraded: the
`independent_grades` field is zero.

## Visual assets

No external images, icon packs, web fonts or CDN scripts are used. All dashboard
graphics are original CSS and inline SVG written for this project. The
screenshots in `screenshots/` are captures of this application.

## Trademarks

NASA names and mission names (BASS-II, FLEX, Saffire) are used descriptively to
identify the cited research. No trademark licence is granted or implied.
