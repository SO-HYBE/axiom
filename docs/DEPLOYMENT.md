# Deployment

AXIOM is one Python process serving one HTML page and a JSON API. It needs no
database, no build step and no background worker. This document covers local
startup, Docker, host configuration, persistence and the verification that was
actually performed.

> **Status:** verified locally and in Docker on the development machine on
> 2026-11-11. **No public deployment has been performed**, because no hosting
> account, domain or credentials were provided. Do not treat this repository as
> having a public URL.

## 1. Local production-style start

```bash
python -m venv .venv
.venv/bin/python -m pip install --no-index --find-links wheelhouse -e .
.venv/bin/python -m axiom serve --host 127.0.0.1 --port 8767
```

On Windows use `.\.venv\Scripts\python.exe`. The development command

```bash
python -m axiom serve --port 8767
```

remains valid and is the recommended local command. Defaults are
`--host 127.0.0.1 --port 8765`, so pass `--port 8767` to match the documented
URL.

Startup refuses to serve if `data/processed/chunks.jsonl` is missing:

```text
AXIOM: Scientific corpus is missing; run python -m axiom ingest first
```

## 2. Docker

```bash
docker compose up --build
```

The image:

- is based on `python:3.12-slim`;
- installs `pypdf==6.13.0` from the bundled `wheelhouse/`, so the build does not
  require PyPI;
- runs as unprivileged user `axiom` (uid 10001);
- binds `0.0.0.0:8767` inside the container;
- exposes a `HEALTHCHECK` that calls `/healthz` every 30 seconds.

Without Compose:

```bash
docker build -t axiom:1.0.0 .
docker run --rm -p 8767:8767 \
  -e AXIOM_ALLOWED_HOSTS=localhost:8767 \
  -v axiom-scenarios:/app/runs/scenarios \
  axiom:1.0.0
```

### VPS quick start

Copy the checkout without the local virtual environment or secrets, then build on
the server:

```bash
rsync -av --exclude .venv --exclude .env --exclude .git \
  ./ deploy@server:/opt/axiom/
ssh deploy@server
cd /opt/axiom
printf 'AXIOM_ALLOWED_HOSTS=axiom.example.org,axiom.example.org:443\n' > .env
docker compose up -d --build
curl --fail http://127.0.0.1:8767/healthz
```

The Compose project name is pinned to `axiom`, so the persistent volume is
`axiom_scenarios` regardless of the checkout directory. Point the DNS
record at the server, open ports 80/443, and terminate TLS with the reverse proxy
in section 5. Keep port 8767 closed to the public internet.

## 3. Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `AXIOM_HOST` | no | `127.0.0.1` | Bind address. Containers set `0.0.0.0` |
| `AXIOM_PORT` | no | `8765` | Listening port (container uses `8767`) |
| `AXIOM_ALLOWED_HOSTS` | for public access | empty | Comma-separated `Host` values to accept outside loopback |
| `AXIOM_ALLOWED_ORIGINS` | for a split frontend | empty | Comma-separated browser origins allowed to call the API |
| `AXIOM_LOG_REQUESTS` | no | `0` | `1` writes one access-log line per request to stderr |
| `GROQ_KEY` | no | empty | Enables live Groq answers |
| `OPENROUTER_KEY` | no | empty | Enables live OpenRouter answers |
| `GROQ_MODEL` | no | provider default | Fixed Groq model ID |
| `OPENROUTER_MODEL` | no | provider default | Fixed OpenRouter model ID |
| `AXIOM_PUBLISH_PORT` | no | `8767` | Compose-only host port |

Copy `.env.example` to `.env` for local use. Never commit `.env`.

## 4. Host header configuration

The service validates the HTTP `Host` header before doing any work. Loopback
names for the listening port are always accepted. Any other name must be
declared:

```bash
python -m axiom serve --host 0.0.0.0 --port 8767 \
  --allowed-host axiom.example.org --allowed-host axiom.example.org:443
```

or:

```bash
AXIOM_ALLOWED_HOSTS=axiom.example.org,axiom.example.org:443
```

If the proxy forwards a `Host` that is not listed, clients receive `403
{"error":"Invalid host"}`. This is intentional: it blocks DNS-rebinding access
to a public listener. Include the port in the value when the public URL uses a
non-default port.

`POST` and `OPTIONS` requests with an undeclared `Origin` receive `403`. The
default is same-origin-only, so no CORS grant is sent to other sites.

### Split-origin static frontend

The dashboard can also be hosted separately from the API. Declare the exact
frontend origins:

```bash
python -m axiom serve --host 0.0.0.0 --port 8767 \
  --allowed-host api.example.org \
  --allowed-origin https://app.example.org
```

or:

```bash
AXIOM_ALLOWED_HOSTS=api.example.org
AXIOM_ALLOWED_ORIGINS=https://app.example.org
```

Only declared origins receive `Access-Control-Allow-Origin`, and `OPTIONS`
preflights are answered for the five JSON `POST` paths. The page's
Content-Security-Policy also adds the declared origins to `connect-src`. The
dashboard reads its API origin from `config.js` (`window.AXIOM_API_BASE`); the
Python service serves that file with an empty value for same-origin use, and a
static build rewrites it. See [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md) for the
verified free-tier split.

## 5. Reverse proxy

Terminate TLS at the proxy and forward to the container port. Preserve the
original `Host` header, or rewrite it to a value listed in
`AXIOM_ALLOWED_HOSTS`.

Caddy example:

```caddy
axiom.example.org {
    reverse_proxy 127.0.0.1:8767 {
        header_up Host {host}
    }
}
```

nginx example:

```nginx
server {
    listen 443 ssl;
    server_name axiom.example.org;

    location / {
        proxy_pass http://127.0.0.1:8767;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

The service does not read `X-Forwarded-*`; configure the `Host` value instead.

## 6. Persistence

| Location | Survives process restart | Survives container replace | Survives `docker compose down -v` |
|---|---|---|---|
| `runs/scenarios/` on the host (local run) | yes | n/a | n/a |
| `axiom-scenarios` named volume | yes | yes | **no** |
| Container writable layer | no | no | no |

The Compose file mounts the named volume `axiom-scenarios` at
`/app/runs/scenarios`. Anything written outside that path is temporary
container storage.

Back up and restore:

```bash
docker run --rm -v axiom_scenarios:/data -v "$PWD":/backup \
  alpine tar czf /backup/scenarios.tgz -C /data .
```

```bash
docker run --rm -v axiom_scenarios:/data -v "$PWD":/backup \
  alpine tar xzf /backup/scenarios.tgz -C /data
```

Saved assessments are plain JSON files named `<scenario_id>.json`. They can be
copied between environments.

## 7. Health checks and logging

- `GET /healthz` returns `200` when the corpus and inventory load, with chunk,
  source and ingested-source counts. It returns `503` otherwise and never
  reveals filesystem paths.
- The Docker `HEALTHCHECK` uses `/healthz`.
- Access logging is off by default. Set `AXIOM_LOG_REQUESTS=1` or pass
  `--log-requests`.
- Unhandled request errors are returned as JSON with a message that does not
  contain a local path. Startup configuration errors are printed to stderr and
  exit non-zero.

## 8. What was verified

Recorded 2026-11-11 on Windows 11 with Python 3.12 and Docker 28.3.2.

| Check | Result |
|---|---|
| Fresh virtual environment install from `wheelhouse/` | Passed |
| `python -m unittest discover -s tests` | 516 tests, OK, 5 skipped (symlink privilege) |
| `node --test tests/js/dashboard_models.cjs` | 31 tests, pass |
| `python -m axiom serve --port 8767` | Serves dashboard and API |
| `GET /healthz` | `200`, 294 chunks, 12 ingested sources, 19 inventory entries |
| `GET /` | Dashboard HTML served |
| Scenario assessment in the running app | Saved, exported and reopened |
| Docker image build | Passed (`axiom:1.0.0`) |
| `docker compose up -d` | Container reached `healthy` |
| Assessment inside the container | Saved to the named volume |
| `docker compose restart` | Scenario reopened unchanged |
| `docker compose down` then `up -d` | Scenario still present in the volume |
| Undeclared `Host: public.example` | `403` |
| Declared host via `AXIOM_ALLOWED_HOSTS` | `200` |
| Public internet deployment | **Not performed** |

### Final submission tree re-verification, 2026-11-14

The clean submission copy was re-tested from a fresh virtual environment built
only from `wheelhouse/`.

| Check | Result |
|---|---|
| Fresh virtual environment install from `wheelhouse/` | Passed (Python 3.12.10) |
| `python -m unittest discover -s tests` | 652 tests, OK, 5 skipped |
| `node --test tests/js/dashboard_models.cjs` | 32 tests, pass |
| `python -m axiom serve --host 127.0.0.1 --port 8767` | Serves dashboard and API |
| `GET /healthz` | `200`, 294 chunks, 12 ingested sources, 19 sources |
| `GET /api/resources` and the three `/api/axiom/*` result endpoints | `200` |
| `POST /api/axiom/trace-demo` | `200` for a valid preset |
| Undeclared `Host` / declared `Host` | `403` / `200` |
| Docker image build | Passed (`axiom:1.0.0`) |
| `docker run` health, dashboard and resources endpoints | Passed |
| Scenario saved in the mounted volume, then container restart | Record still present |
| `docker compose up -d` | Container reached `healthy`, `GET /healthz` returned `200` |
| Static frontend served on a second local origin | Dashboard loaded; `/api/status` returned `200` through CORS |
| Cross-origin `POST /api/axiom/trace-demo` after preflight | `200` |
| `node scripts/render_static_config.mjs` | Produced `dist/index.html` and `dist/config.js` |
| `render.yaml` | Prepared for a free static site and free Python API; **not synced** |
| Public internet deployment | **Not performed** |

## 9. Not verified

- A real public URL, DNS, TLS certificate or CDN.
- Multi-user concurrency, load testing or horizontal scaling.
- A managed platform's filesystem semantics. If a platform uses an ephemeral
  filesystem and cannot mount a volume, scenario persistence will be lost on
  redeploy. Prefer a platform with a persistent volume, or accept ephemeral
  scenario storage and treat exports as the durable record.

## 10. Production checklist

1. Set `AXIOM_ALLOWED_HOSTS` to the exact public host.
2. Keep one process per persistent volume; do not run multiple replicas that
   write to the same scenario directory without a shared filesystem.
3. Terminate TLS at a proxy.
4. Leave model provider keys unset unless live answers are needed.
5. Back up `runs/scenarios/`.
6. Point the platform health check at `/healthz`.
7. Confirm `GET /healthz` returns `200` after every deploy.
8. Do not expose the service on a public interface without an allowed-host list.
