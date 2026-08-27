# Deploying to Railway

Railway runs real containers, so the deployed app is the same architecture as
local — separate worker, real queue, leasing, single-flight. Nothing is degraded
to fit a serverless model.

Cost: new accounts get $5 credit for 30 days with no card, which covers a
submission window. After that it's $5/month minimum.

---

## Before you start

**Confirm your key is not in git:**

```bash
git status --short          # .env must NOT appear
git ls-files | grep -c "^\.env$"    # must print 0
```

`.env` is in `.gitignore`, but check anyway — a leaked key on a public repo gets
scraped within minutes.

Push the repo to GitHub if you haven't; Railway deploys from it.

---

## What you'll create

Five things in one Railway project:

| Service | Source | Purpose |
|---|---|---|
| `postgres` | Railway plugin | Database |
| `redis` | Railway plugin | Queue + cache |
| `api` | `backend/` | FastAPI |
| `worker` | `backend/` | Pipeline execution |
| `frontend` | `frontend/` | Static bundle + `/api` proxy |

Both `api` and `worker` build from the same `backend/` directory — same image,
different start command.

---

## Steps

### 1. Create the project and add the plugins

New Project -> Deploy from GitHub repo -> pick this repo.

Then **+ New -> Database -> PostgreSQL**, and again for **Redis**. Railway
injects `DATABASE_URL` and `REDIS_URL` automatically. You never copy them by hand.

> The app rewrites Railway's `postgresql://` scheme to `postgresql+asyncpg://`
> at startup (`core/config.py`), so the injected value works unchanged.

### 2. The `api` service

- **Root directory**: `backend`
- **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Pre-deploy command**: `alembic upgrade head`

  This replaces Compose's one-shot `migrate` container. Railway runs it before
  each deploy goes live, so the schema is always ahead of the code.
- **Networking**: enable a public domain only if you want to hit the API
  directly. The frontend proxies to it privately, so it is not required.

Variables:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your key>
GENERATOR_MODEL_ID=gemini-3.7-flash
REVIEWER_MODEL_ID=gemini-3.7-flash
LLM_MAX_CONCURRENCY=4
LLM_REQUESTS_PER_MINUTE=14
```

### 3. The `worker` service

**+ New -> GitHub Repo -> same repo** (a second service from the same source).

- **Root directory**: `backend`
- **Start command**: `python -m app.worker`
- **Replicas: 1** — see the warning below.
- Same variables as `api`.

> ### Keep the worker at exactly 1 replica
> The requests-per-minute limiter (`services/rate_limit.py`) is **process-local**.
> Two workers means two independent 14/min budgets against one 15/min provider
> quota, so you would be rate-limited constantly.
>
> To scale horizontally you must either set `LLM_REQUESTS_PER_MINUTE=0` and rely
> on the provider's own 429s, or replace the limiter with a Redis-backed one
> shared across processes.

### 4. The `frontend` service

**+ New -> GitHub Repo -> same repo.**

- **Root directory**: `frontend`
- **Networking**: generate a public domain. **This is the URL you share.**
- Variable:

```
API_UPSTREAM=http://<api-service-name>.railway.internal:8000
```

Use the exact service name Railway shows for the api service. The nginx config is
a template rendered at container start, so this is substituted then — nothing is
baked into the JavaScript bundle at build time.

### 5. Check it

1. `https://<your-domain>/health` -> `{"status":"ok","checks":{...}}`
   A 503 here means Postgres or Redis is not reachable; the body names which.
2. Open the domain, generate **Grade 4 / "Types of angles"**.
3. Watch the worker logs in Railway while it runs — you should see the job
   claimed, the stages persisted, then completion.

---

## After deploying

**Rate-limit the public endpoint.** The link is public and every request spends
your Gemini quota. The cache absorbs repeat topics, but unique topics cost
quota directly. Free tier is 1,500 requests/day; one lesson is 2-6 requests, so
roughly 250-700 lessons/day before it stops working for everyone.

**Keep the deployed prompt versions in sync.** Bumping `PROMPT_VERSIONS`
invalidates the cache by design — expect the first requests after a deploy to be
slower because they regenerate.

**Watch the daily quota.** When it runs out, jobs fail with
`provider_daily_quota_exhausted`, which the UI shows as "Today's AI limit is
reached" rather than a generic error.

---

## Switching back to Claude

If you later add Anthropic credits, no code changes:

```
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
GENERATOR_MODEL_ID=claude-opus-5
REVIEWER_MODEL_ID=claude-opus-5
LLM_REQUESTS_PER_MINUTE=0
LLM_MAX_CONCURRENCY=15
```

The model IDs are part of the cache key, so switching provider invalidates cached
content automatically — no Gemini-generated lesson is ever served as a Claude one.
