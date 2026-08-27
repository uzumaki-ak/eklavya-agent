# Eklavya — Agent-Based Educational Content Pipeline

Two AI agents produce grade-appropriate lessons, and the UI shows the whole
handoff rather than just a final answer.

- **Generator Agent** — drafts an explanation plus multiple-choice questions for a `(grade, topic)` pair.
- **Reviewer Agent** — judges that draft on age appropriateness, conceptual correctness, and clarity.
- **One refinement pass** — if the Reviewer fails the draft, the Generator re-runs once with the feedback embedded. Capped at one pass, enforced structurally in the graph.

**Live:** <https://sincere-perfection-production-95aa.up.railway.app> — try Grade 4
"Types of angles" for a clean pass, or Grade 1 "quantum entanglement" to watch the
Reviewer reject a draft and the refinement get judged in turn.

Full design rationale and the review history behind it: [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Quick start

```bash
cp .env.example .env          # add your GEMINI_API_KEY
docker compose up --build
```

Open <http://localhost:3000>.

The API is not published to the host — the frontend container reverse-proxies
`/api` to it, so everything is same-origin (no CORS, no baked-in API URL).

---

## How the pipeline works

```
moderate topic ─► generate draft ─► review ─┬─ pass ─────────────────────► done
                                            └─ fail ─► refine once ─► review ─► done
```

Every stage is persisted separately (`original_output`, `initial_review`,
`refined_output`, `final_review`) so the UI can show the draft, the critique, and
the rewrite side by side — including on a cache hit.

A Reviewer **fail** is always shown to the user with its feedback; that
transparency is the point. Only moderation blocks are withheld.

---

## Project layout

```
backend/
  app/
    agents/      Generator + Reviewer, provider adapters, prompts
    pipeline/    LangGraph state, nodes, routing, job runner, single-flight
    db/          SQLAlchemy models + repositories (leasing, flights)
    services/    cache, canonicalization, moderation, queue, lease guard
    api/routes/  FastAPI endpoints
    schemas/     Pydantic contracts (the assessment's I/O spec)
  alembic/       migrations
  tests/
frontend/
  src/
    components/  UI, including hand-drawn SVG icon set
    hooks/       job lifecycle
    lib/         API client, fun facts
    styles/      split stylesheets
loadtest/        locust scenario
```

Conventions: Python is `snake_case` / `PascalCase` classes (PEP 8); JS is
`camelCase` with `PascalCase` component files; DB columns and JSON fields are
`snake_case`. No file exceeds 200 lines.

---

## Production concerns this handles

| Concern | Approach |
|---|---|
| Provider rate limits | Semaphore caps in-flight calls; one-process RPM safety cap; Tenacity retries transient provider/network errors and honours retry hints |
| Runaway jobs | One hard `asyncio.timeout_at` per job (120s), above which the run terminates cleanly |
| Duplicate work | Postgres job leasing with a fencing token; a superseded worker cannot commit |
| Duplicate submissions | `Idempotency-Key` bound to a request hash; reuse with a different payload returns `409` |
| Repeat topics | Versioned exact-match Redis cache storing the full envelope |
| Thundering herd on a new topic | Single-flight election in `content_flights`; followers reuse the leader's result |
| Child safety | Topic and every generated output moderated independently; check failures fail closed with a distinct status |
| Malformed model output | Native structured output plus a bounded schema-repair loop for cross-field rules |

---

## Testing

```bash
cd backend && pip install -e ".[dev]" && pytest
```

Covers the schema contract (including the cross-field rules the API cannot
enforce), cache-key canonicalization, and graph routing — notably that the
one-refinement cap holds even when the second review also fails.

### Reviewer evaluation baseline

Run on **2026-08-28** with **Gemini `gemini-3.5-flash-lite`**:

This result applies only to that model. The repository and `.env.example` default
to `gemini-3.7-flash`, which has not been measured by this baseline.

| Metric | Result |
|---|---:|
| Scored cases | 12/12 |
| Defect recall | 8/8 (100%) |
| Good-lesson recall | 4/4 (100%) |
| Balanced accuracy | 100% |
| Topic-drift flag | 11/12 (92%) |

All cases pass the Generator schema and reach the Reviewer. One on-topic lesson
with an untaught quiz question was incorrectly marked off-topic, although its
overall `fail` verdict was correct. This is a small, hand-labelled baseline, not
a production quality claim; rerun
`python -m tests.run_reviewer_eval` after changing the model or Reviewer prompt.

### Load test

```bash
pip install locust
locust -f loadtest/locustfile.py --host http://localhost:3000
```

Set 100 users / spawn rate 10. `POST /api/generate` should stay in the tens of
milliseconds — it only enqueues. Job *completion* time is dominated by provider
latency and your rate limit, not by this stack, so a fast enqueue with slower
completions is the expected shape. 429s mean `LLM_MAX_CONCURRENCY` is set higher
than your API tier allows.

When `LLM_REQUESTS_PER_MINUTE` is non-zero, keep one worker because that limiter
is process-local. Horizontal scaling requires disabling it and relying on the
provider quota, or replacing it with a distributed project-wide limiter.
