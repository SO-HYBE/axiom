# Vercel deployment (free-tier demo)

AXIOM can be served as one static frontend plus one Python Function. The browser uses same-origin `/api/...` requests; no API URL secret or CORS setting is needed. The function reuses the existing HTTP route handler, with rewrites preserving the requested AXIOM endpoint for dispatch.

## Project settings

- Import this repository into a Vercel personal Hobby project.
- Framework preset: **Other**.
- Root directory: repository root.
- Build command: `node scripts/render_static_config.mjs` (also in `vercel.json`).
- Output directory: `dist`.
- Install command: leave automatic; Python dependencies are declared in `pyproject.toml`.
- No start command. Vercel rewrites `/api/*` and `/healthz` to the `api/index.py` function and passes the original path in an internal query parameter.
- Deploy region and all usage must stay within Hobby's included limits. Hobby is intended for personal, non-commercial use; confirm the project qualifies before using that plan.

The Python runtime is supported by Vercel. AXIOM's corpus is about 5.8 MB and is read from the deployment bundle. The function allows the apex domain, `www`, and the deployment host values supplied by Vercel.

## Runtime behavior and limits

- The static frontend and backend share an origin, so the generated `config.js` leaves `AXIOM_API_BASE` empty.
- The function reads the shipped corpus and benchmark artifacts from the repository. It writes run, comparison, and scenario records under the platform's temporary directory. That history is **ephemeral**, instance-local and can disappear at any time; it is not a database or durable user storage. Scenario/run listing works only for records visible in that function instance.
- No model API key is required for extractive mode. Groq/OpenRouter need user-provided API keys and are external services that may have separate quotas or pricing; they are optional and are not configured by this repository. Ollama requires an externally reachable Ollama server and is not suitable as a free Vercel-hosted dependency.
- The function has a 60-second maximum configured. Slow provider calls can time out; use extractive mode for the most reliable demo. Vercel Hobby has monthly usage limits and its published policy restricts Hobby use to personal, non-commercial projects.
- Do not put secrets in source control. If optional provider keys are used, configure them as Vercel environment variables and review that provider's costs first.

## Custom domain

Add `axiomcombustion.us` to the Vercel project and follow the exact DNS values Vercel shows for that project. DNS targets can differ by domain/project, so use Vercel's displayed records rather than guessing. Keep Porkbun nameservers and add/edit only the records Vercel asks for. Add `www.axiomcombustion.us` only if it is also attached in Vercel. DNS changes are intentionally not performed by this preparation.

## Verify after a manual deployment

Open `/healthz` and confirm `status` is `ok`; then load the home page, check `/api/status`, and submit one extractive question. A successful answer may report `saved_locally: false` because the deployment does not provide durable storage.
