## Context — reviewing a provider abstraction added after your GO

You previously green-lit this implementation for live testing. Live testing then failed for a non-code reason: the Anthropic account has **$0 credits** and no free trial available in the user's region (India), so every call returned `400 invalid_request_error — Your credit balance is too low`. The user cannot spend money on this.

Two calls were made before stopping; both were rejected at the billing check before generating tokens, so nothing was consumed. That failure did validate the whole pipeline end to end — nginx `/api` proxy → FastAPI → run row created → SAQ enqueue → worker pickup → DB lease claim → single-flight election → provider call → error caught, terminalized as `generator_error`, job finished cleanly. The 400 was correctly **not** retried, since it isn't in the retry predicate.

Google Gemini has a genuinely free API tier (no card, ~15 req/min, 1500 req/day), so the code was refactored to support both providers. **Review that refactor.**

Same evidence bar as every previous round: cite the actual API/signature/doc behind each claim, and say explicitly when you cannot verify something rather than asserting it.

### What changed

**New package `app/agents/providers/`** — replaces the previously Anthropic-hardcoded `client.py`:
- `base.py` — `LLMProvider` Protocol (`generate`, `is_retryable`, `retry_after`) and `LLMRoleConfig` (moved here from `client.py`).
- `claude.py` — the original Anthropic path, unchanged in behaviour. Still `AsyncAnthropic(max_retries=0)`, still uses `messages.parse(output_format=...)` / `parsed_output`, still treats 408/409/5xx + RateLimit/Timeout/Connection as retryable and everything else (401/400/403) as permanent.
- `gemini.py` — new. Uses `google-genai`: `client.aio.models.generate_content(model=..., contents=user, config=types.GenerateContentConfig(system_instruction=..., max_output_tokens=..., response_mime_type="application/json", response_schema=PydanticModel))`, reading `response.parsed`. Treats `genai_errors.APIError` with code in {408,429,500,502,503,504} as retryable. Parses Gemini's `"retryDelay": "27s"` out of the error body via regex to honour its own backoff hint. A `None` `response.parsed` raises `ValueError` so the existing schema-repair loop handles it.
- `__init__.py` — `get_provider()` selected by `settings.llm_provider` (`"claude"` | `"gemini"`), lazily imported and `lru_cache`d, plus the shared `GENERATOR_CONFIG` / `REVIEWER_CONFIG`.

**`client.py` rewritten** — `call_claude` renamed to `call_llm`, now provider-agnostic. Signature changed from `messages: list[dict]` to `user: str` (both agents updated). Retry predicate now delegates to `provider.is_retryable(e)`; `_clamped_wait` now delegates to `provider.retry_after(e)`. The deadline stop, per-attempt deadline check, semaphore-inside-retry, transport counters, and per-call `asyncio.timeout` are all unchanged.

**New `app/services/rate_limit.py`** — `RequestsPerMinuteLimiter`, a sliding-60s-window limiter acquired **outside** the semaphore in `call_llm`. Rationale: the semaphore caps concurrency, not rate, and Gemini's free tier is 15 requests/*minute*, so a burst of short calls could exhaust the quota without ever exceeding concurrency. Raises `PipelineDeadlineExceeded` if waiting would pass the job deadline. Disabled when `llm_requests_per_minute <= 0`.

**Config** — `llm_provider` (default `"gemini"`), `gemini_api_key`, `llm_requests_per_minute` (default 14), `llm_max_concurrency` lowered 15 → 4 for the free tier. Model IDs defaulted to `gemini-3.7-flash`.

**Imports moved** — `db/runs.py` and `services/cache.py` now import `GENERATOR_CONFIG`/`REVIEWER_CONFIG` from `app.agents.providers` instead of `app.agents.client`.

**Dependency** — added `google-genai>=1.60` to `pyproject.toml`.

### Verified locally after the refactor
All Python compiles; no stale `call_claude` references remain; no file exceeds 200 lines. **Nothing has run against Gemini yet** — no key was available at the time of writing.

### Specific things to check

1. **`google-genai` API correctness** — verify against the current SDK that `client.aio.models.generate_content(...)`, `types.GenerateContentConfig(system_instruction=..., response_mime_type=..., response_schema=<PydanticModel>)`, and `response.parsed` are the correct current bindings, and that `max_output_tokens` is the right parameter name. Confirm `google.genai.errors.APIError` exposes a `.code` attribute as `gemini.py` assumes. **I could not verify any of this at runtime.**

2. **Model ID currency** — `gemini-3.7-flash` was chosen from a web search claiming an Aug 13 2026 release, with `gemini-3.6-flash` noted as the older stable fallback. Confirm both IDs are real, currently served, and on the free tier. I got this wrong once already (originally wrote `gemini-2.5-flash`, which is two generations stale), so please check rather than assume.

3. **Rate limiter correctness** — `RequestsPerMinuteLimiter.acquire()` releases `self._lock` before sleeping and re-loops. Check for: a lost-wakeup or starvation bug under concurrency, whether the timestamp is correctly recorded at acquire rather than completion, and whether the `min(wait_for, 1.0)` re-check loop can busy-spin. Also confirm placing it outside the semaphore is right, and that raising `PipelineDeadlineExceeded` from inside the Tenacity-wrapped `_attempt` correctly terminates rather than being retried (it is deliberately not in the retry predicate).

4. **Provider abstraction leaks** — confirm nothing outside `providers/` still assumes Anthropic. In particular check that `_clamped_wait` calling `get_provider()` per retry is safe, and that the `lru_cache` on `get_provider()` doesn't cause problems across the API and worker processes.

5. **Cache identity** — the digest includes `GENERATOR_CONFIG.model_id` / `REVIEWER_CONFIG.model_id`, so switching provider changes the model IDs and therefore invalidates cached content. Confirm that actually holds, and that no cached Claude-generated content could be served while running Gemini.

6. **Anthropic path still intact** — confirm `LLM_PROVIDER=claude` still works exactly as it did when you green-lit it, so a Claude demo needs only credits and a config change.

7. Anything that breaks on `docker compose up --build` with the new dependency, and anything in the Docker/Compose setup that the new env vars require but that is missing.

### Output

Group by severity: (a) breaks at import/startup, (b) breaks at runtime on the first real Gemini call, (c) breaks only under concurrency/rate-limit pressure, (d) quality. For each: file:line, what's wrong, evidence, concrete fix. Then a clear go / no-go for live testing against Gemini.
