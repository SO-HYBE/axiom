# Render deployment (free tier)

> **Status:** configuration prepared and verified locally on 2026-11-14.
> **Nothing has been deployed and no DNS record has been changed.** No Render
> account, API key or service exists for this repository yet, and no public URL
> is claimed. This document is the exact procedure for a later $0 deployment.

AXIOM is split into two free Render services:

| Service | Render type | Runtime | Public name |
|---|---|---|---|
| Dashboard | static site | `static` | `axiomcombustion.us` (custom), `www` redirect, `axiom-web.onrender.com` |
| JSON API | web service | `python` | `axiom-api.onrender.com` |

The backend is the repository's standard-library `http.server` service, not
FastAPI. Render therefore needs no ASGI server, database or background worker.

## 1. Local checks

| Check | Result |
|---|---|
| Python suite | 652 discovered; local HTTP cases could not bind sockets in the sandbox; one release-hygiene check reports the pre-existing missing `docs/RULES_AND_ELIGIBILITY.md`; 5 skipped |
| Dashboard JavaScript suite | Included in Python discovery and passed |
| Static build script | Passed with `RENDER=true` and `API_BASE_URL=https://axiom-api.onrender.com`; produced `dist/index.html` and `dist/config.js` |
| Earlier local split-origin check (before the package rename) | The prior record reports dashboard load, `GET /api/status` and `POST /api/axiom/trace-demo` succeeding through CORS; not rerun because this sandbox denies local socket binds |
| Backend `/config.js` | The service code still serves its same-origin default; current runtime socket test could not run in this sandbox |
| Render deployment | **Not performed** |
| DNS changes | **Not performed** |

The split-origin test used a static copy of the dashboard whose `config.js`
pointed at `http://127.0.0.1:8767`, while the API allowed exactly
`http://127.0.0.1:5500`. No wildcard CORS rule was used.

## 2. Build and start commands

### Static frontend

| Setting | Value |
|---|---|
| Build command | `node scripts/render_static_config.mjs` |
| Publish directory | `dist` |
| Build-time variable | `API_BASE_URL=https://axiom-api.onrender.com` |

The script copies `src/axiom/web/index.html` to `dist/index.html` and writes
`dist/config.js` containing `window.AXIOM_API_BASE = "<API_BASE_URL>"`. It
refuses to build on Render without `API_BASE_URL`, and it rejects values with a
path, query or credentials.

### Python API

| Setting | Value |
|---|---|
| Build command | `pip install -r requirements.txt && pip install .` |
| Start command | `python -m axiom serve --host 0.0.0.0 --port $PORT` |
| Health check path | `/healthz` |
| Plan | `free` |

`render.yaml` in the repository root contains both services. The service names
are significant because they determine the `onrender.com` hostnames used in the
CORS and CSP configuration.

## 3. Can the frontend be a static site?

Yes. The dashboard is one self-contained HTML page with inline CSS and
JavaScript, inline SVG icons, system fonts and no framework, package manager,
image bundle or server-side rendering. The only runtime input is the API origin,
which is now read from `window.AXIOM_API_BASE` in `config.js`.

All API calls go through a small `api(path)` helper, so the same page works:

- **Same origin** when served by the Python service (`config.js` default is `""`).
- **Split origin** when served by a static host (`config.js` is rewritten at build
  time).

Render static sites have no runtime environment variables. Changing
`API_BASE_URL` requires a rebuild, which is why it is a build-time variable.

## 4. Environment variables

### Static site

| Variable | Value | Purpose |
|---|---|---|
| `API_BASE_URL` | `https://axiom-api.onrender.com` | Baked into `dist/config.js` |

Do not put provider keys or any other secret on the static site; every static
asset is public.

### API web service

| Variable | Required | Value in `render.yaml` | Purpose |
|---|---|---|---|
| `PYTHON_VERSION` | recommended | `3.12.10` | Matches the locally tested interpreter |
| `AXIOM_HOST` | no | `0.0.0.0` | Render requires a public bind address |
| `AXIOM_ALLOWED_HOSTS` | yes | `axiom-api.onrender.com` | Accepts the Render hostname |
| `AXIOM_ALLOWED_ORIGINS` | yes for split origin | apex, `www`, static `onrender.com` origin | Exact browser origins allowed to call the API |
| `AXIOM_LOG_REQUESTS` | no | `0` | `1` adds request lines to stderr |
| `GROQ_KEY` | no | not set | Optional live Groq answers |
| `OPENROUTER_KEY` | no | not set | Optional live OpenRouter answers |
| `GROQ_MODEL` / `OPENROUTER_MODEL` | no | not set | Optional fixed model IDs |

`AXIOM_ALLOWED_HOSTS` and `AXIOM_ALLOWED_ORIGINS` are comma-separated. Origins
are compared exactly after normalising case and default ports. A trailing slash
is accepted but no path is allowed. Add or remove origins whenever a frontend
hostname changes.

Provider keys, if used, must be added in the Render Dashboard, never in
`render.yaml` or the static build. Core retrieval, claim checks, scenario
comparison, planning, saved demonstrations and the recorded AXIOM panels need no
key at all.

## 5. External dependencies and free-tier limits

| Dependency | Needed? | Notes |
|---|---|---|
| PyPI at build time | yes | `pypdf` and the build backend; Render has network access during builds |
| Groq / OpenRouter | optional | Only for live model answers; not called by core endpoints |
| Ollama | no | Not available on Render |
| Database / Redis | no | Not used |
| Persistent disk | no | Not available on the free web-service plan |

Free web-service behaviour:

- The API spins down after 15 minutes without traffic; the next request wakes it
  and can take roughly a minute. The static site does not spin down.
- The filesystem is ephemeral. Every restart, redeploy or spin-down discards
  written files.
- One instance means no horizontal scaling and no shared in-memory state.
- Monthly bandwidth and build-pipeline allowances are shared across the
  workspace. Render can suspend free services/builds at included-usage limits
  when no payment method is on file. For a strict $0 ceiling, do not add a
  payment method, do not upgrade, and accept suspension if an included limit is
  reached. Free static sites and Free web services are covered by Render's
  included free offering; usage limits still apply.

## 6. Persistence and filesystem assumptions

| Path | Read/write | Survives a Render restart? |
|---|---|---|
| `data/processed/chunks.jsonl`, `data/sources.json`, `data/conditions.jsonl` | read-only | Yes, restored from the Git deploy |
| `runs/axiom/`, `runs/benchmarks/`, `runs/demos/` | read-only shipped artifacts | Yes, restored from the Git deploy |
| `runs/scenarios/` | written by the scenario endpoints | **No** |
| `runs/runs/`, `runs/comparisons/` | written by live answers/comparisons | **No** |
| `runs/model_cache/` | written by live provider calls | **No** |

Consequences:

- The dashboard and all recorded evidence work after a cold start because they
  are read from deployed files.
- A scenario saved through the UI is available until the service restarts or
  redeploys. The list returns to empty afterwards. This is a platform limit, not
  a silent success: the API still reports `saved_locally: true` for the current
  instance, and the deployment documentation records the limit.
- Live model answers and comparisons are also ephemeral on this plan.
- There is no free persistent disk. A paid disk would move the deployment off
  the $0 budget. To retain scenarios, export the JSON locally or keep using the
  Docker/Compose deployment with its named volume.

## 7. Deployment steps (not executed yet)

1. Push this repository to a Git provider that Render can read. The local
   checkout currently has no Git remote.
2. In Render, create a **Blueprint** from the repository. Render reads
   `render.yaml` and proposes the two services above, both free.
3. Confirm the static service uses `node scripts/render_static_config.mjs`,
   publish path `dist`, and `API_BASE_URL=https://axiom-api.onrender.com`.
4. Confirm the API service uses the Python runtime, the free plan, the commands
   in section 2, and `/healthz` as its health check.
5. Let both builds finish. Before DNS, verify the Render URLs directly:
   `https://axiom-api.onrender.com/healthz` and
   `https://axiom-web.onrender.com/`.
6. Add `axiomcombustion.us` as a custom domain on the static service. Render
   automatically adds `www.axiomcombustion.us` and redirects it to the apex.
7. Create the Porkbun DNS records in section 8, then click **Verify** for each
   custom domain in Render. Render issues the TLS certificate after verification.
8. Re-test the public site and API, including the browser console, to confirm no
   CSP or CORS errors.
9. Only then announce a public URL. Until step 8 succeeds, no public deployment
   exists.

## 8. Exact Porkbun DNS records

The free Hobby workspace includes **two custom domains across all services**.
Adding the apex domain automatically adds its `www` redirect, so both are used by
the frontend. The API deliberately stays on `axiom-api.onrender.com`, which needs
no custom domain. That keeps the setup at exactly $0.

In Porkbun: **Domain Management → DNS Records → Manage**.

| Host | Type | Answer / target | TTL | Notes |
|---|---|---|---|---|
| blank (root) | `ALIAS` | `axiom-web.onrender.com` | `600` | Preferred for the apex. Porkbun may display the root as blank or `@` |
| `www` | `CNAME` | `axiom-web.onrender.com` | `600` | Render redirects `www` to the apex |
| `api` | none | none | — | The API uses its free `onrender.com` hostname |

Use the service hostname shown in Render after the static service is created if
Render assigned a suffix because `axiom-web.onrender.com` was unavailable. Do
not guess a different host. Render documents the custom-domain setup and its
automatic `www` redirect in [Custom Domains](https://render.com/docs/custom-domains);
Porkbun documents blank Host values for the apex and its DNS record fields in
[Add DNS Records](https://kb.porkbun.com/article/231-how-to-add-dns-records-on-porkbun).

Additional requirements:

1. **Delete existing `A` and `AAAA` records for the root and `www`** that
   Porkbun created for parking or forwarding. They conflict with the records
   above. Do not create any new `AAAA` record: Render uses IPv4.
2. Leave `MX`, `TXT` (including SPF/DKIM), `CAA` and other unrelated records
   alone.
3. If Porkbun does not offer `ALIAS` for this domain, Render's documented
   alternative for an apex is an `A` record to `216.24.57.1`. Prefer `ALIAS`
   when it is available.
4. If the domain has `CAA` records, allow `letsencrypt.org` and `pki.goog`, or
   Render cannot issue the TLS certificate.
5. In Render, open the static service's **Settings → Custom Domains** and click
   **Verify** next to the apex and `www` entries. DNS propagation can take a few
   minutes.

### Optional branded API (not enabled, $0 alternative)

If a branded API hostname matters more than the `www` frontend, use exactly two
custom domains instead:

| Host | Type | Answer / target |
|---|---|---|
| blank (root) | `ALIAS` | `axiom-web.onrender.com` |
| `api` | `CNAME` | `axiom-api.onrender.com` |

Then remove the automatically added `www` domain in Render, add
`api.axiomcombustion.us` to the API service, and update:

- static `API_BASE_URL` → `https://api.axiomcombustion.us`
- static CSP `connect-src` → `https://api.axiomcombustion.us`
- API `AXIOM_ALLOWED_HOSTS` → `axiom-api.onrender.com,api.axiomcombustion.us`
- API `AXIOM_ALLOWED_ORIGINS` → `https://axiomcombustion.us`

`www.axiomcombustion.us` will not resolve in this variant unless Porkbun URL
forwarding is configured separately. Keeping the default configuration in
`render.yaml` (apex + `www`, API on `onrender.com`) avoids that gap.

A third custom domain (`api.axiomcombustion.us` **and** apex **and** `www`) costs
$0.25/month on the Hobby plan. It is intentionally not configured.

## 9. Verification commands

Replace hostnames if the service names change.

```bash
# API readiness (expects 200 and a JSON body with chunk counts)
curl -i https://axiom-api.onrender.com/healthz

# Static page and runtime configuration
curl -i https://axiomcombustion.us/
curl -s https://axiomcombustion.us/config.js

# CORS preflight from the public frontend origin
curl -i -X OPTIONS https://axiom-api.onrender.com/api/scenario-assess \
  -H "Origin: https://axiomcombustion.us" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"

# A disallowed origin must not receive an Access-Control-Allow-Origin header
curl -i https://axiom-api.onrender.com/api/status \
  -H "Origin: https://attacker.example"
```

The preflight should return `204` with
`Access-Control-Allow-Origin: https://axiomcombustion.us`. The last request may
return `200` (public data) but must not grant CORS to the attacker origin.

In the browser, open the dashboard and confirm the source library, resource
report and AXIOM panels load. The Network panel should show requests to
`https://axiom-api.onrender.com/api/...`, not to the static host. The Console
should show no Content-Security-Policy or CORS errors.

## 10. Rollback

1. Remove the custom domains from the Render static service.
2. Suspend or delete both Render services.
3. In Porkbun, delete the `ALIAS`/`CNAME` records added above and restore any
   previous parking or forwarding records if desired.
4. The repository, Docker image and local deployment are unaffected.

## 11. Cost boundary

This blueprint requests only free resources: a static site and one free web
service. It does not request a disk, database, Key Value instance, paid instance
type, paid custom domain or subscription. The two custom domains fit the Hobby
allowance because the API uses its `onrender.com` hostname. Bandwidth and build
minutes are metered; exceeding the included amounts can incur charges, so keep
the demo small and do not enable paid features.
