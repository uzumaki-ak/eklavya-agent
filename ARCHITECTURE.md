# Eklavya AI Assessment — Architecture Plan

**Revision 8 — IMPLEMENTED.** Updated 27 Aug 2026 after an independent evaluation
against the assignment brief.

Rev 8 fixes what that evaluation found: moderation failed in both directions, the
Reviewer was never told the topic (so it approved a lesson on the wrong subject),
`refinement_count` was lost on both reuse paths, a rejected rewrite still offered a
playable quiz, and this document claimed constants and tests that did not exist.
Constants below are checked against `app/core/config.py`; the Testing section lists
only tests that run.

## Source requirement (from assessment PDF)

**Generator Agent** — input `{"grade": int, "topic": str}`, output `{"explanation": str, "mcqs": [{"question": str, "options": [str,str,str,str], "answer": str}]}`. Language must match grade level, concepts correct, structure deterministic.

**Reviewer Agent** — formal input: Generator's output JSON only. Output `{"status": "pass"|"fail", "feedback": [str, ...]}`. Evaluates age appropriateness, conceptual correctness, clarity. Spec's I/O contract omits grade; `target_grade` injected as pipeline context.

**Refinement**: on `fail`, re-run Generator once with feedback embedded. Hard cap of one pass.

**UI (mandatory)**: displays Generator output, Reviewer feedback, and refined output (if any) as distinct stages — including on cache hits.

Audience: school-age kids. Target scale: "1000s of users," low-hundreds concurrent LLM calls at peak.

---

## Orchestration: LangGraph "Reflection" pattern

```python
class AgentState(TypedDict):
    grade: int
    topic: str
    original_output: dict | None
    initial_review: dict | None
    refined_output: dict | None
    final_review: dict | None
    refinement_count: int
    schema_repair_attempts: int
    transport_attempts_total: int
    logical_llm_calls: int
    failure_stage: str | None    # None | "generator_error" | "reviewer_error" | "moderation_blocked" | "moderation_error"
    error_code: str | None
    pipeline_deadline: float
```

```
moderate_topic → blocked/error → END
  → clear: generate_original → deadline/retries exhausted: "generator_error" → END
      → success: [moderate output — inlined in generate_original_node] → blocked/error → END
          → clear: review_original → deadline/retries exhausted: "reviewer_error" → END (never fabricate a verdict)
              → pass: END
              → fail: refine_once (writes ONLY refined_output)
                  → [moderate output — inlined in refine_node] → blocked/error → END
                  → clear: review_refined → END regardless of pass/fail
```

A Reviewer **fail** (even final) is still shown with feedback. Moderation block/error is suppressed, tracked as two distinct statuses. `add_conditional_edges`, `set_entry_point`, `END` confirmed current in LangGraph 1.2.11.

## Structured output: provider-native behind one interface

```python
@dataclass(frozen=True)
class LLMRoleConfig:
    role: str
    model_id: str
    max_tokens: int

GENERATOR_CONFIG = LLMRoleConfig("generator", settings.generator_model_id, 4096)
REVIEWER_CONFIG = LLMRoleConfig("reviewer", settings.reviewer_model_id, 2048)

# Claude: messages.parse(..., output_format=PydanticModel)
# Gemini: aio.models.generate_content(...,
#   config=GenerateContentConfig(response_mime_type="application/json",
#                                response_json_schema=PydanticModel.model_json_schema()))
```

Both agents call the `LLMProvider` protocol. `LLM_PROVIDER` selects the adapter;
model IDs remain explicit configuration because IDs are provider-specific. Claude
sets `max_retries=0`; Gemini leaves `HttpRetryOptions` unset, so Tenacity remains
the single retry authority.

`temperature` removed entirely from all requests and from the cache identity — narrowing the previous claim per round 4: the Python SDK v1.0 raises `TypeError` if `temperature`/`top_p`/`top_k` are passed at all (a client-side removal, applies regardless of model); the API-level 400-on-non-default-value behavior is specifically documented for Claude Opus 4.7+ and Mythos Preview, not universally every active model. Either way we don't send it.

Pin `anthropic==1.1.0` and `google-genai==2.19.0`.

### MCQ validation

```python
class MCQ(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    answer: str

    @field_validator("question", "answer")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @model_validator(mode="after")
    def validate_answer_and_options(self):
        normalized = [o.strip() for o in self.options]
        if any(not o for o in normalized):
            raise ValueError("options must not be blank")
        if len(set(normalized)) != 4:
            raise ValueError("options must be four distinct strings")
        if self.answer.strip() not in normalized:
            raise ValueError("answer must match one of the four options")
        return self
```

Cross-field rules raise local `pydantic.ValidationError`, not caught by the transport-retry decorator — handled by a separate bounded schema-repair loop (below).

## Concurrency & resilience

**Fixed (round 4, points 2 and 3)**: the deadline was previously a soft check re-evaluated before each attempt — it didn't cover semaphore waits, and Tenacity's backoff could sleep past it regardless. Now one outer `asyncio.timeout_at(deadline)` wraps the *entire* pipeline (semaphore waits, retries, repair loops, follower waits — everything), which is the actual hard boundary. A pipeline-level timeout is explicitly distinguished from a per-call timeout so the former is terminal, not retried.

```python
PIPELINE_DEADLINE_SECONDS = 120   # hard internal budget; SAQ job timeout (150s) is a ~30s cleanup margin above it, not the primary guard

class LLMCallTimeout(Exception): pass
class PipelineDeadlineExceeded(Exception): pass

def _is_retryable_status(exc: BaseException) -> bool:
    return isinstance(exc, APIStatusError) and (exc.status_code in (408, 409) or exc.status_code >= 500)

def _parse_retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    try:
        return float(header) if header is not None else None
    except (TypeError, ValueError):
        return None

def _clamped_wait(deadline: float):
    def wait(retry_state) -> float:
        exc = retry_state.outcome.exception()
        retry_after = _parse_retry_after(exc)   # read from exc.response.headers, not a nonexistent exc.retry_after
        base = retry_after if retry_after is not None else wait_exponential_jitter(initial=1, max=20)(retry_state)
        return max(0.0, min(base, deadline - time.monotonic()))
    return wait

def _deadline_stop(deadline: float):
    def stop(retry_state) -> bool:
        return time.monotonic() >= deadline
    return stop

async def call_anthropic(config: LLMRoleConfig, messages, output_format, deadline: float):
    if time.monotonic() >= deadline:
        raise PipelineDeadlineExceeded()   # never issue a request once the budget is already gone

    @retry(
        stop=stop_after_attempt(2) | _deadline_stop(deadline),   # clamping the wait to 0 doesn't stop retrying — a separate stop condition is required
        wait=_clamped_wait(deadline),
        retry=retry_if_exception(
            lambda e: isinstance(e, (RateLimitError, APITimeoutError, APIConnectionError, LLMCallTimeout)) or _is_retryable_status(e)
        ),
        reraise=True,
    )
    async def _attempt():
        if time.monotonic() >= deadline:
            raise PipelineDeadlineExceeded()   # checked again per-attempt so no HTTP request starts after expiration;
                                                # not in the retry predicate above, so Tenacity reraises it immediately, never retries it
        async with llm_semaphore:
            try:
                async with asyncio.timeout(30):   # per-call cap; the outer timeout_at (below) is the real deadline enforcement
                    response = await client.messages.parse(
                        model=config.model_id, max_tokens=config.max_tokens,
                        messages=messages, output_format=output_format,
                    )
                    return response.parsed_output
            except TimeoutError as e:
                raise LLMCallTimeout() from e   # per-call timeout only — a pipeline-level timeout never reaches here, see run_pipeline
    return await _attempt()

async def generate_with_repair(config, prompt, deadline, max_repair_attempts: int = 2) -> GeneratorOutput:
    validation_feedback = ""
    for attempt in range(max_repair_attempts + 1):
        try:
            return await call_anthropic(config, build_messages(prompt, validation_feedback), GeneratorOutput, deadline)
        except ValidationError as e:
            if attempt == max_repair_attempts:
                raise
            validation_feedback = f"Your previous response failed validation: {e}. Fix and resend."

async def run_pipeline(run_id, grade, topic) -> None:
    deadline = time.monotonic() + PIPELINE_DEADLINE_SECONDS
    try:
        async with asyncio.timeout_at(deadline):   # the actual hard boundary — covers semaphore waits, backoff sleeps, follower waits, everything inside
            await execute_graph(run_id, grade, topic, deadline)   # LangGraph invocation
    except (TimeoutError, PipelineDeadlineExceeded):
        # TimeoutError here = the outer timeout_at fired; PipelineDeadlineExceeded = call_llm's own pre-attempt
        # check caught it first. Same terminal outcome either way — not retried.
        await mark_terminal(run_id, failure_stage=current_stage_of(run_id), error_code="pipeline_deadline_exceeded")
    finally:
        async with asyncio.timeout(30):   # cleanup runs outside the cancelled scope, with its own short bound
            await persist_terminal_state_and_release_lease(run_id)
```

**Request ceiling**: one `call_llm` invocation has at most 2 Tenacity attempts,
but the 120-second outer pipeline deadline is the controlling wall-clock bound.
Gemini 3.7 runs at `thinking_level="low"` for this simple educational workload;
Google documents that level for minimizing latency and cost. A 40-second call
watchdog, two transport attempts, and a 120-second whole-job deadline prevent
the UI from waiting for several minutes. Track `transport_attempts_total` and
`logical_llm_calls`.

Pin `tenacity==9.1.4`. No gateway: the app has two direct adapters but exactly
one active provider per deployment.

## Queue/worker: SAQ + Redis

Pin `saq[redis]==0.26.4`. SAQ job timeout **150s** — ~30s cleanup margin above the 120s internal deadline, not the primary guard (the outer `timeout_at` above is). Heartbeat enabled, refreshed by a background task every 10s for the life of the job (a single call at start does not survive a multi-minute pipeline). Sweep interval, heartbeat threshold, shutdown grace period kept consistent and shorter than 150s. SAQ's `key` dedupes *enqueue* only — see Idempotency & job leasing for the real correctness boundary.

## Idempotency & job leasing

**Fixed (round 4, point 4)**: renewal was previously prose with no actual wiring — `call_llm` had no run/lease context, and a retry sequence (up to 180s) could outlast a 2-minute lease with nothing renewing it. Also corrected a wrong claim: expiry alone doesn't reject a write — a write is only rejected once another worker has actually reclaimed the row (Postgres serializes the competing updates; this is safe, but the earlier test description implied expiry itself was the trigger, which is inaccurate). Fixed with a background lease-guard task and a `lease_epoch` that changes only on takeover (not on every stage write, unlike the old `row_version`):

```
current_stage, lease_owner, lease_expires_at, lease_epoch bigint default 0
```

```sql
-- claim/takeover — ONLY this bumps lease_epoch
UPDATE generation_runs SET lease_owner=$worker, lease_expires_at=now()+interval '2 minutes', lease_epoch=lease_epoch+1
WHERE id=$run_id AND (lease_owner IS NULL OR lease_expires_at < now())
RETURNING lease_epoch;   -- 0 rows → someone else holds a valid lease

-- renewal, via a background asyncio.Task started alongside the pipeline run, every 30-40s
-- for as long as ANY pipeline work is active (semaphore waits, backoff, follower waits, everything) — does NOT bump epoch
UPDATE generation_runs SET lease_expires_at=now()+interval '2 minutes'
WHERE id=$run_id AND lease_owner=$worker AND lease_epoch=$my_epoch
RETURNING lease_epoch;   -- 0 rows → epoch changed (reclaimed) → cancel the pipeline task immediately, don't wait for its next checkpoint

-- every stage write, fenced against the epoch, does NOT bump it
UPDATE generation_runs SET original_output=$data, current_stage='original_generated'
WHERE id=$run_id AND lease_owner=$worker AND lease_epoch=$my_epoch
RETURNING lease_epoch;   -- 0 rows → epoch changed, discard this result, do not commit
```

The background guard is one task per running job rather than scattering renewal calls through every node/retry callback — simpler to reason about, and it can cancel the pipeline's main task the moment renewal fails instead of waiting for the next natural checkpoint.

**Guarantee, stated precisely**: idempotent HTTP submission, at-least-once provider-call execution, fenced (exactly-once) persistence. A worker can receive a valid LLM response and crash before committing it — that's a duplicate *provider call*, never a duplicate *stored result*, since any write from a superseded epoch is rejected.

**HTTP contract**: client may send `Idempotency-Key` on `POST /generate`; reuse with a different `(grade, topic)` returns `409`, not a silent reuse:

```sql
INSERT INTO generation_runs (session_id, idempotency_key, request_hash, grade, topic_original, ..., status)
VALUES ($1, $2, $3, $4, $5, ..., 'queued')
ON CONFLICT (session_id, idempotency_key) DO NOTHING
RETURNING *;
-- no row: SELECT existing. request_hash mismatch → 409. Else return the existing
-- pointer; if it is still queued with no lease, retry the same deduplicated enqueue.
```

## Caching

**Fixed (round 4, point 1)**: the `content_flights` claim query previously assumed a follower gets back a row showing the leader's identity — but Postgres's `INSERT ... ON CONFLICT DO UPDATE ... WHERE ... RETURNING` returns **zero rows**, not the existing row, whenever the `WHERE` clause blocks the update (i.e. exactly the follower case, when someone else's flight is legitimately active). A follower has to fall back to a separate `SELECT`. Also added: a `'failed'` terminal state so followers don't wait forever on a crashed leader, a shorter renewable lease (a 5-minute flight lease was uncomfortably close to the SAQ job timeout), fenced leader-completion, follower polling with jitter bounded by the follower's own deadline, and a durable `result_run_id` so a completed result survives Redis eviction.

```sql
content_flights(
  cache_digest text PRIMARY KEY,
  leader_run_id uuid, lease_expires_at timestamptz, fencing_token int default 0,
  status text CHECK (status IN ('in_progress','done','failed')),
  result_run_id uuid null   -- durable pointer to the generation_runs row holding the actual computed content
)

-- attempt election — returns a row ONLY if we won.
-- 'done' is deliberately NEVER a takeover condition: a request that reaches election just after
-- the leader finishes must fall through to the follower path and reuse result_run_id, not recompute.
INSERT INTO content_flights (cache_digest, leader_run_id, lease_expires_at, fencing_token, status)
VALUES ($digest, $run_id, now() + interval '45 seconds', 1, 'in_progress')
ON CONFLICT (cache_digest) DO UPDATE
  SET leader_run_id=$run_id, lease_expires_at=now()+interval '45 seconds',
      fencing_token=content_flights.fencing_token+1, status='in_progress'
WHERE content_flights.status = 'failed'
   OR (content_flights.status = 'in_progress' AND content_flights.lease_expires_at < now())
RETURNING leader_run_id, fencing_token;
-- 0 rows (including the 'done' case) → we're a follower: SELECT leader_run_id, status, result_run_id FROM content_flights WHERE cache_digest=$digest
```

**Leader**: renews its `content_flights` row every **~15s** against the 45s flight lease (a tighter cadence than the job lease-guard's 30-40s, which is fine against its own much longer 2-minute lease — these are two independent renewal loops tuned to their own lease durations, not one shared cadence). Flight loss is an explicit signal to the runner: it cancels only the graph task, not SAQ's outer handler, then terminalizes and releases its own run without touching the replacement leader's flight. Renewal stays active through final persistence. On success, the leader persists the completed `generation_runs` envelope/status **and** flips `content_flights` to `done` in **one transaction** — `done` must never become visible before the referenced run is durably complete:

```sql
BEGIN;
UPDATE generation_runs SET status='completed_pass', ... WHERE id=$run_id AND lease_owner=$worker AND lease_epoch=$my_epoch;
UPDATE content_flights SET status='done', result_run_id=$run_id
  WHERE cache_digest=$digest AND leader_run_id=$run_id AND fencing_token=$token
  RETURNING *;   -- 0 rows → leadership was reclaimed: roll back BOTH writes,
                 -- then terminalize/release this losing run separately; never cache it
COMMIT;
```
On error, the same fenced pattern sets `status='failed'` (single statement, no transaction needed since there's no paired write).

**Follower**: polls with jitter (500ms, backing off to 2s, capped), bounded by its own `PIPELINE_DEADLINE_SECONDS`, while also renewing its own job lease throughout (it's still "processing" its own row the whole time it waits). On `status='done'`: read `result_run_id`'s `generation_runs` row and copy the envelope into the follower's own row with `cache_hit=true`, complete its job. On `status='failed'` or an expired `lease_expires_at`: re-run the election query itself — this naturally works since the `WHERE` clause already allows takeover once a flight has failed or expired.

**Cache key** — uses the same `GENERATOR_CONFIG`/`REVIEWER_CONFIG` objects the call site uses (zero drift possible), no `temperature`:

```python
def cache_key(grade: int, canonical_topic: str) -> str:
    identity = {
        "grade": grade, "topic": canonical_topic,
        "provider": settings.llm_provider,
        "generator_model": GENERATOR_CONFIG.model_id, "generator_max_tokens": GENERATOR_CONFIG.max_tokens,
        "reviewer_model": REVIEWER_CONFIG.model_id, "reviewer_max_tokens": REVIEWER_CONFIG.max_tokens,
        "generator_prompt_version": PROMPT_VERSIONS["generator"], "reviewer_prompt_version": PROMPT_VERSIONS["reviewer"],
        "schema_version": SCHEMA_VERSION, "canonicalizer_version": CANONICALIZER_VERSION,
        "moderation_policy_version": MODERATION_POLICY_VERSION,
    }
    return "cache:v5:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
```

**Cache only clean, completed envelopes** — never `moderation_blocked`/`moderation_error`/`generator_error`/`reviewer_error`; only `completed_pass`/`completed_fail`, full envelope, satisfying the 3-stage UI display on a hit.

Provider-side prompt/context caching, when enabled, remains separate from the
application result cache and is not a substitute for it.

## Persistence: Postgres

```
generation_runs(
  id, session_id, idempotency_key, request_hash,
  grade, topic_original, topic_canonical, canonicalizer_version,
  status text NOT NULL CHECK (status IN (
    'queued','processing','completed_pass','completed_fail',
    'generator_error','reviewer_error','moderation_blocked','moderation_error'
  )),
  current_stage, lease_owner, lease_expires_at, lease_epoch bigint NOT NULL DEFAULT 0,
  cache_hit,
  generator_model, reviewer_model, generator_prompt_version, reviewer_prompt_version, schema_version,
  moderation_results jsonb,
  original_output jsonb, initial_review jsonb, refined_output jsonb null, final_review jsonb null,
  refinement_count smallint CHECK (refinement_count BETWEEN 0 AND 1),
  transport_attempts_total smallint, schema_repair_attempts smallint, logical_llm_calls smallint,
  token_usage jsonb, error_code text null,
  created_at, started_at, completed_at
)

UNIQUE (session_id, idempotency_key);
CREATE INDEX generation_runs_history_idx ON generation_runs (session_id, created_at DESC);
CREATE INDEX generation_runs_topic_idx ON generation_runs (grade, topic_canonical, created_at DESC)
  WHERE status IN ('completed_pass', 'completed_fail');

content_flights(cache_digest PRIMARY KEY, leader_run_id, lease_expires_at, fencing_token, status, result_run_id)
```

`row_version` renamed to `lease_epoch` throughout — it now only changes on takeover (ownership), not on every content write, matching standard fencing-token semantics more precisely.

**Stretch (phase 2)**: append-only `generation_run_events` audit table; `pg_trgm` on `topic_canonical` for admin-only near-duplicate discovery.

PostgreSQL 18-compatible schema.

## Safety: content moderation

Moderate topic before generation; moderate `original_output`/`refined_output` independently before exposure. Flag → `moderation_blocked`, terminates, never shown. Service failure → `moderation_error`, distinct status, fails closed with different messaging/telemetry. Each check persisted independently in `moderation_results`.

**Matching intent, not nouns.** The first filter matched bare words (`sex`, `drugs`,
`bomb`) and expected the noun before the verb for weapons. On a school product that
is the wrong shape, and it failed in *both* directions — verified live:

| Topic | Old filter | Now |
|---|---|---|
| "sexual reproduction in plants" | blocked | allowed |
| "why drugs are harmful to the body" | blocked | allowed |
| "sexism in the workplace" | blocked | allowed |
| "how to make a bomb at home" | **allowed** | blocked |
| "ways to hurt yourself" | **allowed** | blocked |

A topic is now blocked when it pairs an *instruction- or acquisition-seeking intent*
with a *harmful object*, or matches a short list of phrases harmful under any
framing. Nouns alone never block. A help-seeking override means "how to help someone
who self-harms" reads as educational rather than as a request for method.
`tests/test_moderation.py` pins all 18 cases in both directions.

> **Still demo-grade, and this matters.** It is a high-precision local pre-filter,
> not production child safety: it cannot reason about context, and an obfuscated
> request will get through. **Replace it with a hosted classifier before real
> children use this.** Bumping `moderation_policy_version` (now `v3`) invalidates
> content cached under the old rules — without that, lessons the broken filter
> cleared would keep being served.

## Reviewer agent quality (LLM-as-judge grounding)

Binary `pass`/`fail` per spec. Each `feedback` item cites a specific sentence or
question number.

**The Reviewer is given the topic, and topic coverage is enforced in code.** It
previously received only grade and content, which made its own coverage criterion
unevaluable — and produced a live failure: Grade 1 / "quantum entanglement" came
back as an *approved* lesson about solids and liquids. Three changes:

1. `REVIEWER_USER` now interpolates the topic, so criterion 4 can actually fire.
2. The model answers into `ReviewerJudgement`, which carries a required internal
   `addresses_requested_topic: bool`. A `False` there **forces** `status="fail"`
   in a Pydantic validator. Missing/invalid fields enter the same bounded schema-
   repair policy as Generator output and fail closed as a Reviewer error only if
   repair is exhausted. This
   enforces the model's self-report; it does not independently detect drift if the
   model incorrectly reports `True`. The field is dropped by `to_output()` before
   the response reaches the API, so the public shape remains `{status, feedback}`.
3. The Reviewer is instructed never to ask for the topic to be replaced (it is
   reviewing a draft, not renegotiating the request), and the refinement prompt is
   told to ignore any such instruction if one arrives anyway. Two layers, because
   the prompt rule is advisory and the validator is not.

**Measured, not tuned.** `tests/reviewer_golden_set.py` holds 12 hand-labelled cases
(8 fail, 4 pass), including the two known live misses (elimination-only distractors,
near-duplicate options). The evaluator reports both class recalls, a confusion
matrix, balanced accuracy, and topic-flag accuracy; schema-rejected cases are
skipped rather than credited to the Reviewer. Deliberately no tuning yet.

The user-supplied topic is wrapped in `<topic>` tags with both prompts stating that
its contents are the subject to teach, never instructions — it is untrusted input
being interpolated into a prompt.

### Answer position is fixed in code, not asked for in the prompt

A second live defect: the model writes the correct answer first and pads with
distractors afterwards, so the quiz was answerable without reading it. In a live
sample of nine questions the answer sat at index 0 six times and index 1 three
times, and never lower. `app/agents/option_order.py` reorders each question's
options with a permutation seeded from the question and its own option set —
deterministic, so regeneration and cache reuse agree; idempotent, because the list
is sorted before shuffling; and applied after validation, so the answer is already
known to be one of the four and a permutation cannot break that. It runs inside
`GeneratorAgent.run`, which means the Reviewer judges the same order the child
sees. Prompting for randomness was the obvious alternative and was rejected:
models self-randomise position badly, and an advisory rule cannot be tested.

Validation also rejects choices whose meaning depends on the original position
(`All of the above`, `Both A and B`, label-prefixed choices, and ordinal option
references). The Generator's existing bounded schema-repair path then regenerates
the MCQ before the deterministic permutation runs. Cache schema `v6` prevents
pre-fix lessons with those choices from being reused.

## Observability (optional/stretch)

Self-hosted Langfuse if tracing is added. Not required for the core submission.

## API layer: FastAPI

- `POST /generate {grade, topic}` (optional `Idempotency-Key`) → `202 {job_id}`, or `409` on key/payload mismatch
- `GET /jobs/{job_id}` → `{status, original_output, initial_review, refined_output, final_review}`
- Optional `GET /jobs/{job_id}/stream` (SSE)
- Health check endpoint (`/health` readiness, `/health/live` liveness)
- **No HTTP rate limiting.** `services/rate_limit.py` caps LLM requests per minute,
  which is a provider-quota guard, not request throttling. A public deployment is
  therefore unauthenticated and unthrottled — see DEPLOYMENT.md.

## Frontend

**Fixed (round 4, point 5)**: `VITE_API_URL` set as a Compose runtime `environment:` variable does nothing for a production Vite build — Vite bakes `import.meta.env.VITE_*` values in at *build* time, not container start time, so a value set after the image is built has no effect. Fixed by serving the built frontend behind a same-origin reverse proxy rather than baking an absolute API URL in at all:

Stepper UI — grade+topic form → live cards for Generating → Reviewing → (Refining) → Done, human-readable + raw JSON per stage. Reviewer `fail` always shown with feedback; only moderation-blocked/error content withheld. Frontend calls a same-origin `/api/*` path; the container's own Nginx/Caddy proxies that to `api:8000` internally — no build-time endpoint baking, no CORS configuration needed. Stack (React/Vite vs plain HTML) still open, but whichever is chosen keeps this same-origin-proxy approach.

## Docker Compose

```yaml
services:
  postgres:
    image: postgres:18.6
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10
    volumes:
      - postgres_data:/var/lib/postgresql
    restart: unless-stopped

  redis:
    image: redis:8.10.1
    command: ["redis-server", "--appendonly", "yes"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10
    volumes:
      - redis_data:/data
    restart: unless-stopped

  migrate:
    build: ./backend
    command: ["alembic", "upgrade", "head"]
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }

  api:
    build: ./backend
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    env_file: .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5
    depends_on:
      migrate: { condition: service_completed_successfully }
      redis: { condition: service_healthy }
    restart: unless-stopped

  worker:
    build: ./backend
    command: ["python", "-m", "app.worker"]
    env_file: .env
    depends_on:
      migrate: { condition: service_completed_successfully }
      redis: { condition: service_healthy }
    restart: unless-stopped

  frontend:
    build: ./frontend           # built assets + Nginx/Caddy reverse-proxying /api -> api:8000, same origin
    ports: ["3000:3000"]
    depends_on:
      api: { condition: service_started }
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
```

`api` no longer publishes a host port directly — it's reached only through the frontend container's reverse proxy at `/api/*`, removing the need for any absolute cross-origin URL. No `version:` key; document minimum supported Compose CLI version.

## Testing

`cd backend && pytest` — 140 tests. This section lists only tests that exist; an
earlier revision described an intended suite as though it were implemented, which
is exactly the kind of claim a reviewer checks.

**What is covered**

| File | Covers |
|---|---|
| `test_schemas.py` (14 functions; 7 position cases parametrised) | The spec's I/O contract: four distinct, position-independent options, answer among them, no blanks, `extra="forbid"`, binary reviewer status, fail-requires-feedback |
| `test_pipeline_routing.py` (10) | Graph routing, and that the one-refinement cap holds even when the second review also fails |
| `test_topic_fidelity.py` (14) | Required topic judgement, forced off-topic failure, delimiter escaping, single-flight envelope reuse, evaluator baselines |
| `test_reviewer_repair.py` (4) | Reviewer schema repair success, bounded exhaustion, required fields, all eval cases schema-valid |
| `test_option_order.py` (7) | MCQ option order is stable, idempotent, lossless, and spreads the answer across all four positions |
| `test_provider_refactor.py` (8) | Provider abstraction, retry predicates, config/cache-key coherence |
| `test_moderation.py` (4, parametrised over 57 topics) | Curriculum topics pass; plainly phrased harm requests are blocked; the output gate runs the same rules |
| `test_runner_resilience.py` (4) | Deadline termination, flight-leadership loss, rollback-then-terminalize |
| `test_canonicalize.py` (4) | Cache-key normalisation and its alias map |
| `test_rate_limit.py` (3) | Sliding-window RPM limiter |

**Reviewer evaluation set** — `tests/reviewer_golden_set.py` holds 12 hand-labelled
cases (8 fail, 4 pass), including good on-topic, coherent-but-off-topic, factual,
age-level, question-quality, distractor-quality, and topic-coverage examples. Run
`python -m tests.run_reviewer_eval` — it needs an API key and spends quota, so it
is a script rather than part of `pytest`. Read balanced accuracy and both class
recalls, not raw agreement; an always-pass or always-fail Reviewer scores only 50%
balanced accuracy.

**What is deliberately NOT covered, and why**

- **Leasing, fencing, single-flight, idempotency** have no integration tests.
  They need a live Postgres and concurrent workers; `test_runner_resilience.py`
  covers the logic paths with fakes, which is not the same thing. Treat these as
  reasoned-about rather than proven.
- **Reviewer prompt tuning.** The golden set measures; nothing tunes against it
  yet. Tuning without a baseline swings into over-rejection, which is worse than
  the leniency it would fix.
- **No CI.** Tests run locally and in the container, not on push.

**Load test** — `loadtest/locustfile.py`, tens/low-hundreds of concurrent
submissions. `POST /api/generate` should stay in the tens of milliseconds since it
only enqueues; completion time is dominated by provider latency.

## Explicitly rejected, with reasoning

- **`instructor`** — superseded by native structured output; incompatible SDK pin at time of review.
- **`arq`** — maintenance-only; SAQ is the stable, asyncio-native alternative.
- **Celery** — stable but a less natural fit than SAQ here.
- **Taskiq** — still Alpha-classified.
- **AI Gateway (Portkey/Bifrost)** — unnecessary for two small direct adapters and one active provider per deployment.
- **Semantic/vector caching** — unnecessary for structured inputs, documented leakage risk.
- **CrewAI alongside LangGraph** — redundant.
- **Raw-HTTP-throughput scaling patterns** — wrong problem.
- **Redis-based single-flight lock** — replaced with Postgres `content_flights`, one locking primitive across the system instead of two.
- **Runtime-injected frontend API URL** — Vite bakes env vars at build time; replaced with a same-origin reverse-proxy approach.

## Verified stable pins (confirmed current as of Codex review round 4, 27 Aug 2026)

```
anthropic==1.1.0
langgraph==1.2.11
saq[redis]==0.26.4
tenacity==9.1.4
postgres:18.6 (Docker image)
redis:8.10.1 (Docker image)
Compose: rolling spec, no version: key — document minimum supported Compose CLI version
```

---

## Codex review log

**Round 1**: 6/8 points required changes — applied in rev 2. LangGraph-drop recommendation considered, not applied.

**Round 2**: confirmed LangGraph-keep reasonable. 9 further bugs fixed in rev 3.

**Round 3**: 8 further issues fixed in rev 4, three independently spot-checked before applying (temperature removal, `anthropic==1.1.0`, Redis version).

**Round 4**: 5 further issues, all applied in rev 5. One (`max_retries=0` missing) was a self-inflicted regression from the rev 4 rewrite, not a new finding. The other four were real gaps: `content_flights`'s `RETURNING` clause doesn't behave the way a follower needed (Postgres returns zero rows, not the existing row, when the `WHERE` blocks the conflict update — fixed with a fallback `SELECT`, a `'failed'` terminal state, shorter renewable leases, fenced completion, jittered bounded follower polling, and a durable `result_run_id`); the 240s deadline was a soft per-attempt check, not an actual hard boundary — fixed with one outer `asyncio.timeout_at` wrapping the whole pipeline and a distinction between per-call and pipeline-level timeouts; lease renewal was prose with no wiring — fixed with a background renewal task and a `lease_epoch` that only changes on takeover, not every write; and a Vite runtime-env-var approach that does nothing in a production build — fixed with a same-origin reverse-proxy frontend instead of an injected absolute URL.

**Round 5** (final — architecture confirmed ready for implementation): 2 surgical fixes applied in rev 6. Clamping `_clamped_wait` to 0 only stopped Tenacity from *sleeping*, not from *retrying* — a separate deadline-aware `stop` condition was needed (`stop_after_attempt(2) | _deadline_stop(deadline)`), plus a pre-attempt check so no HTTP request starts after the budget is gone, plus fixing the Retry-After read (`exc.response.headers`, not a nonexistent `exc.retry_after` attribute). And the `content_flights` election query allowed takeover of a `'done'` flight, meaning a request arriving just after the leader finished would recompute from scratch instead of reusing `result_run_id` — fixed by making `'done'` never a takeover condition (only `'failed'` or an actually-expired `'in_progress'` lease), tightening the flight-lease renewal cadence to ~15s against its 45s lease, and combining the leader's `generation_runs` completion write with the `content_flights` → `done` transition into one transaction so `done` can never become visible before the result is durably persisted.
