# Hosted models

AXIOM loads GROQ_KEY and OPENROUTER_KEY from the project .env without exposing them in the browser. Existing process environment values take precedence. Quoted names/values are accepted. .env is ignored by Git.

From the project directory:

```powershell
$env:PYTHONPATH='src'
python -m axiom serve
```

Open http://127.0.0.1:8765 . Groq is the default UI provider. Its current default model is qwen/qwen3.8-27b, verified against the authenticated model list and a successful structured-response smoke request on November 2, 2026. This is a development choice, not a benchmark winner. The earlier proposed Llama model was unavailable to this account.

```powershell
python -m axiom ask "Where did BASS-II take place?" --provider groq
python -m axiom ask "What did BASS-II investigate?" --provider extractive
python -m axiom ask "What did BASS-II investigate?" --provider ollama --model llama3.2:latest
```

OpenRouter Super VL has passed a live structured-response smoke test. Ultra is configured but its live response has not been verified. Specify a fixed currently available model ID ending in :free using --provider openrouter --model MODEL_ID, or OPENROUTER_MODEL in .env. Paid models and automatic routing are blocked; provider max prices are set to zero. No provider fallback occurs. Groq charges depend on the account plan; the application does not enable billing or change the plan.

Optional GROQ_MODEL overrides the Groq default. Never change providers/models silently during evaluation. Rate limits and selected temporary server errors now receive up to four attempts within a 60-second total budget, with shared request spacing and server-directed cooldowns. Longer quota waits remain explicit failures. See PROVIDER_RELIABILITY.md. Hosted response caching and resumable benchmark generation are implemented; see history/PHASE6_STATUS.md. Model answers and semantic review still follow the conservative existing release policy; a successful provider call does not certify the science.

CLI default has changed to Groq. Use --provider extractive for the previous offline behavior. Do not put keys in commands, screenshots or Git.

## Nemotron alternatives (verified November 2, 2026)

The OpenRouter live catalog lists both with zero prompt/completion prices:

- Nemotron 3 Ultra: nvidia/nemotron-3-ultra-550b-a55b:free (CLI alias: nemotron-ultra)
- Nemotron 3.5 Super VL: nvidia/nemotron-3.5-super-vl:free (CLI alias: nemotron-super-vl)

Use the dashboard's Quick model selection menu, or:

```powershell
python -m axiom ask "Where did BASS-II take place?" --provider openrouter --model nemotron-ultra
python -m axiom ask "Where did BASS-II take place?" --provider openrouter --model nemotron-super-vl
```

Groq remains the default. Switching is explicit. Both choices retain the zero-price routing restriction and no provider fallback. Free capacity and account limits can still reject or delay calls.

Ultra's free catalog entry does not advertise response_format support, so AXIOM requests JSON in the prompt and validates the parsed result. Super VL uses JSON mode. Reasoning is requested disabled for these bounded structured calls; this is not a benchmark of their full reasoning capability. The current AXIOM adapter sends text only: selecting Super VL does not yet add image/video or scanned-PDF ingestion.

Source: https://openrouter.ai/api/v1/models

Live verification: Super VL returned a valid structured draft for a short source-grounded question. The Ultra check was stopped after an extended wait without a response. No Ultra success or model-quality ranking is claimed. All 51 local tests passed.
