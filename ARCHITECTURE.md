# Eklavya AI Assessment — Architecture Plan

**Revision 10 — IMPLEMENTED (Part 2).** Updated 28 Aug 2026.

Rev 8 fixed what an independent evaluation found: moderation failed in both
directions, the Reviewer was never told the topic (so it approved a lesson on the
wrong subject), `refinement_count` was lost on both reuse paths, a rejected rewrite
still offered a playable quiz, and this document claimed constants and tests that
did not exist.

Rev 9 fixed two defects found by using the deployed app rather than by reading it:
the Reviewer could fail open when it omitted its own topic-coverage flag, and the
Generator put the correct answer first in six of nine sampled questions, making the
quiz answerable without reading it.

Rev 10 implements Part 2. Every data shape changed: the explanation is nested and
grade-tagged, the answer is an index rather than text, `teacher_notes` is new, the
review is four 1-5 scores with field-anchored feedback, and a `ContentTags` block
classifies approved work. Two new agents (Refiner, Tagger), two refinements
instead of one, and a `RunArtifact` that is now the source of truth. Part 1's
queue, leasing, caching, single-flight and moderation are unchanged and carried
forward. Constants below are checked against `app/core/config.py`; the Testing
section lists only tests that run.

Three things Part 2 broke that were not obvious from the brief, each now fixed and
tested: the option shuffle silently invalidates `correct_index` unless the index
is re-derived from the answer *text*; `teacher_notes` bypassed the moderation
filter, which fails silently because moderation still returns "clear"; and seven
model calls do not fit a budget sized for four.

## Source requirement (from assessment PDF)

**Generator Agent** — input `{"grade": int, "topic": str}`, output
`{"explanation": {"text", "grade"}, "mcqs": [{"question", "options": [4], "correct_index"}], "teacher_notes": {"learning_objective", "common_misconceptions": [...]}}`.
Validation failure gets exactly one repair retry, then fails gracefully.

**Reviewer Agent** — formal input: Generator's output JSON only. Output
`{"scores": {age_appropriateness, correctness, clarity, coverage} each 1-5, "pass": bool, "feedback": [{"field", "issue"}]}`.
Pass thresholds must be defined and documented; feedback must reference specific
fields. Spec's I/O contract omits grade and topic; both are injected as pipeline
context, because neither age appropriateness nor coverage is judgeable without them.

**Refiner Agent** — improves content using reviewer feedback. Maximum two
refinement attempts, each logged. Still failing → `rejected`.

**Tagger Agent** — classifies **approved content only**: subject, topic, grade,
difficulty, content_type, blooms_level.

**Orchestration (the real test)** — one `RunArtifact` per run: `run_id`, `input`,
ordered `attempts` of `{attempt, draft, review, refined}`, `final` with
`approved | rejected` plus content and tags, and `timestamps`. Deterministic flow,
bounded retries, full audit trail.

**Backend** — `POST /generate` runs the full pipeline and returns the RunArtifact;
`GET /history?user_id=...` returns stored artifacts. Postgres persistence.

**UI (optional in Part 2, retained)**: displays draft, review, and refinement as
distinct stages — including on cache hits.

Audience: school-age kids. Target scale: "1000s of users," low-hundreds concurrent LLM calls at peak.

---

## Orchestration: LangGraph "Reflection" pattern

```python
class AgentState(TypedDict, total=False):
    run_id: str
    user_id: str
    grade: int
    topic: str
    deadline: float          # time.monotonic() cutoff
    started_at: str          # ISO 8601, UTC

    drafts: list[dict]       # drafts[i] is the content reviewed on attempt i+1
    reviews: list[dict]      # reviews[i] is the review of drafts[i]
    tags: dict | None

    refinement_count: int    # hard cap of 2, enforced by the graph's shape
    schema_repair_attempts: int
    transport_attempts_total: int
    logical_llm_calls: int

    failure_stage: str | None    # generator_error | reviewer_error | tagger_error
                                 # | moderation_blocked | moderation_error
    error_code: str | None
    moderation_results: dict
```

Drafts and reviews are **append-only parallel lists**, not fixed slots. Part 1 had
four named fields because there was exactly one refinement; two refinements
produce six artifacts, and naming them `refined_output_2` would make the audit
trail a function of how many slots someone remembered to add. A node returns the
previous list plus one item and never rewrites an earlier entry, which is what
makes cleared content append-only. A moderation-stopped attempt is represented
with `draft: null`, `content_withheld: true`, and a structured moderation result;
the blocked text itself is deliberately not retained or returned by history.

```
moderate ─► generate ─► review_1 ─┬─ pass ──────────────────────────► tag ─► approved
                                  └─ fail ─► refine_1 ─► review_2 ─┬─ pass ─► tag
                                                                   └─ fail ─►
            refine_2 ─► review_3 ─┬─ pass ─► tag ─► approved
                                  └─ fail ──────────► rejected
```

**The two-refinement cap is structural, not counted.** The graph is unrolled and
acyclic: exactly two refine nodes exist, `refine_2` is reachable only from
`review_2`, and `review_3` has no edge to any refinement. A third refinement is
not expressible. A counted loop was the obvious alternative and was rejected —
it converts a guarantee about the graph into a comparison a later edit can get
wrong. `test_pipeline_routing.py` asserts the compiled graph's shape (node set,
inbound edges, no backward edge), not only the routing functions.

`tag` is reachable only from a passing review, which is how "classify approved
content only" is enforced. All three review positions are the *same* node
function: a review node cannot tell which position it occupies, so it cannot
choose its own successor.

A Reviewer **fail** (even final) is still shown with feedback. Moderation-blocked
text is withheld while the attempt and outcome remain auditable; block and check
failure use distinct statuses. `add_conditional_edges`, `set_entry_point`, `END`
confirmed current in LangGraph 1.2.11.

## The RunArtifact: one derivation, two projections

Part 2's non-negotiable is a single object capturing the whole lifecycle. The risk
with adding one to a system that already stores stage columns is obvious: two
representations of the same run that can disagree. Part 1 already lived that bug —
the cache path and the worker path each derived a run's status separately, and the
cache paths always claimed "pass", so a cached failing review was replayed as a
success.

So there is exactly one path from pipeline state to stored data:

```
state ──► envelope ──┬──► RunArtifact      (source of truth, JSONB)
                     └──► summary columns  (queue state, indexing, live progress)
```

`app/services/envelope.py` owns the envelope; `app/pipeline/artifact.py` is the
only place a RunArtifact is constructed. The Part 1 columns survive because
`executor.py` streams them per node to drive the live UI — but with two
refinements there are up to six artifacts and four slots, so they now mean *first
draft, first review, final content, final review*. The middle of the trail lives
only in the artifact. A single-flight follower therefore rebuilds from the
leader's artifact (`envelope_from_artifact`), not from its columns, which would
hand it three of six stages.

Structural invariants are enforced in the schema rather than trusted from the
pipeline, so a malformed audit trail cannot be persisted and later read back as
fact: attempts numbered consecutively from 1, each visible `refined` identical
to the next visible `draft`, withheld content never stored, no refinement after a
passing review, approved runs carrying both content and tags, rejected runs
carrying none.

Identity is never borrowed. A cache hit reuses another run's *content* and builds
its own artifact with its own `run_id`, `user_id`, timestamps and
`cache_hit: true`, so the trail never claims work it did not do.

## Pass thresholds, and why the model is not told them

`correctness` must be 5; `age_appropriateness`, `clarity` and `coverage` must each
be at least 4 (`app/schemas/review.py`). Correctness has no tolerance because a
lesson that is 80% factually right is not 80% acceptable for this audience; the
other three are matters of degree where a judge model's 4-versus-5 call is mostly
noise.

The verdict is **derived, not trusted**. `pass` is recomputed from the scores, the
outstanding feedback, and the topic-coverage flag. A model that returns
`pass: true` beside `correctness: 2` is overruled and the disagreement is logged —
Part 1 already had to overrule exactly that behaviour for topic drift, and making
the whole verdict a pure function generalises it.

The Reviewer is not shown the thresholds. A model told the bar learns to clear it,
which converts a measurement into a formality. Whether the bar is set correctly is
an empirical question, so `run_reviewer_eval` reports the score distribution over
the known-good cases: a dimension few good lessons clear is a miscalibrated bar,
not a strict one.

Feedback must cite a real field path (`explanation.text`,
`teacher_notes.learning_objective`, `mcqs[1].options[2]`). A hallucinated location
is unactionable for the Refiner, so it fails validation and goes back to the model
rather than into the audit trail.

## Timing budget: seven calls, not four

Part 1's worst path was four model calls. Part 2's is seven — generate, review,
refine, review, refine, review, tag — and each can carry its one repair retry, so
fourteen physical calls is the true upper bound. The 120s pipeline deadline was
sized for four and had to move; the failing path is precisely the one a reviewer
will exercise on purpose ("watch it fail twice, then pass").

Three timeouts, strictly ordered so each layer fails inward first and the outer
one never truncates a run that was about to terminate cleanly:

| Layer | Setting | Value |
|---|---|---:|
| Pipeline | `pipeline_deadline_seconds` | 240s |
| Queue | `saq_job_timeout_seconds` | 270s |
| Proxy | nginx `proxy_read_timeout` | 330s |

These are sized, not measured. The right values come from observed provider
latency; what is fixed is the ordering and the requirement that the synchronous
endpoint fail gracefully before the proxy gives up. Note also that at
`llm_requests_per_minute = 14` a single worst-case run consumes half a minute's
budget, so the free-tier demo should not be load-tested while being graded.

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
PIPELINE_DEADLINE_SECONDS = 240   # hard internal budget; SAQ job timeout (270s) leaves cleanup margin above it

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
but the 240-second outer pipeline deadline is the controlling wall-clock bound.
The submitted `gemini-3.5-flash-lite` configuration uses
`thinking_level="medium"`, selected from the measured Reviewer baseline below.
A 40-second call watchdog and two transport attempts bound each provider call.
Track `transport_attempts_total` and `logical_llm_calls`.

Pin `tenacity==9.1.4`. No gateway: the app has two direct adapters but exactly
one active provider per deployment.

## Queue/worker: SAQ + Redis

Pin `saq[redis]==0.26.4`. SAQ job timeout **270s** — ~30s cleanup margin above the 240s internal deadline, not the primary guard (the outer `timeout_at` above is). Heartbeat enabled, refreshed by a background task every 10s for the life of the job (a single call at start does not survive a multi-minute pipeline). Sweep interval, heartbeat threshold, shutdown grace period kept consistent and shorter than 270s. SAQ's `key` dedupes *enqueue* only — see Idempotency & job leasing for the real correctness boundary.

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

**Cache key** — uses the same four role configs and prompt-version map as the call sites (zero drift possible), no `temperature`:

```python
def cache_key(grade: int, canonical_topic: str) -> str:
    identity = {
        "grade": grade, "topic": canonical_topic,
        "provider": settings.llm_provider,
        "generator_model": GENERATOR_CONFIG.model_id, "generator_max_tokens": GENERATOR_CONFIG.max_tokens,
        "refiner_model": REFINER_CONFIG.model_id, "refiner_max_tokens": REFINER_CONFIG.max_tokens,
        "reviewer_model": REVIEWER_CONFIG.model_id, "reviewer_max_tokens": REVIEWER_CONFIG.max_tokens,
        "tagger_model": TAGGER_CONFIG.model_id, "tagger_max_tokens": TAGGER_CONFIG.max_tokens,
        "generator_prompt_version": PROMPT_VERSIONS["generator"],
        "refiner_prompt_version": PROMPT_VERSIONS["refiner"],
        "reviewer_prompt_version": PROMPT_VERSIONS["reviewer"],
        "tagger_prompt_version": PROMPT_VERSIONS["tagger"],
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
  id, session_id, user_id, idempotency_key, request_hash,
  grade, topic_original, topic_canonical, canonicalizer_version,
  status text NOT NULL CHECK (status IN (
    'queued','processing','completed_pass','completed_fail',
    'generator_error','reviewer_error','tagger_error',
    'moderation_blocked','moderation_error'
  )),
  current_stage, lease_owner, lease_expires_at, lease_epoch bigint NOT NULL DEFAULT 0,
  cache_hit,
  generator_model, reviewer_model, tagger_model,
  generator_prompt_version, reviewer_prompt_version,
  refiner_prompt_version, tagger_prompt_version, schema_version,
  moderation_results jsonb,
  run_artifact jsonb,                      -- the terminal Part 2 source of truth
  progress_envelope jsonb,                 -- full recoverable trail while processing
  original_output jsonb, initial_review jsonb,   -- fixed-width summary of the above,
  refined_output jsonb, final_review jsonb,      -- for live progress and indexing
  tags jsonb,
  refinement_count smallint CHECK (refinement_count BETWEEN 0 AND 2),
  transport_attempts_total smallint, schema_repair_attempts smallint, logical_llm_calls smallint,
  token_usage jsonb, error_code text null,
  created_at, started_at, completed_at
)

UNIQUE (session_id, idempotency_key);
CREATE INDEX generation_runs_history_idx ON generation_runs (session_id, created_at DESC);
CREATE INDEX generation_runs_user_history_idx ON generation_runs (user_id, created_at DESC);
CREATE INDEX generation_runs_topic_idx ON generation_runs (grade, topic_canonical, created_at DESC)
  WHERE status IN ('completed_pass', 'completed_fail');

content_flights(cache_digest PRIMARY KEY, leader_run_id, lease_expires_at, fencing_token, status, result_run_id)
```

`row_version` renamed to `lease_epoch` throughout — it now only changes on takeover (ownership), not on every content write, matching standard fencing-token semantics more precisely.

**Two identities, deliberately distinct.** `session_id` is the anonymous caller and
scopes idempotency keys; `user_id` is the explicit, validated owner that
`GET /history` filters on. An IP-derived session is not a user, and treating one as
such would return a stranger's runs to whoever shares a NAT gateway.

**Migration `0002` preserves old rows rather than rewriting them.** `user_id` is
added nullable, backfilled from `session_id`, then made NOT NULL. Pre-Part-2 rows
keep a null `run_artifact`: they were produced under a different content schema,
and manufacturing an artifact for them would put a v6-shaped payload behind a
v7-shaped contract. `GET /history` reports terminal rows without an artifact,
including rows whose schema version is null. Stored artifacts are attempted
regardless of version, so a routine schema bump cannot erase readable audit
history; genuinely incompatible payloads are counted rather than crashing the
whole response.

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
> children use this.** Bumping `moderation_policy_version` (now `v6`) invalidates
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

Part 2 sharpened this considerably. The answer is now `correct_index`, so a
permutation does not merely bias the quiz — it makes every answer *wrong* unless
the index is re-derived. `balanced_mcq` captures the correct option's **text**
before reordering, permutes, then looks the text back up, and returns a
re-validated MCQ rather than mutating in place. This is the single highest-risk
change in the Part 2 migration and has its own regression test asserting the
answer text survives from every one of the four starting positions.

Validation also rejects choices whose meaning depends on the original position
(`All of the above`, `Both A and B`, label-prefixed choices, and ordinal option
references). The Generator's existing bounded schema-repair path then regenerates
the MCQ before the deterministic permutation runs. Cache schema `v6` prevents
pre-fix lessons with those choices from being reused.

The generator prompt (`v7`) states the same rule. Two layers again, for the usual
reason: the prompt rule is advisory and the validator is not — but a model told up
front costs no repair round, and each repair is a whole extra LLM call.

## Observability (optional/stretch)

Self-hosted Langfuse if tracing is added. Not required for the core submission.

## API layer: FastAPI

Two surfaces, one pipeline.

**Required (Part 2), unprefixed as specified:**
- `POST /generate {grade, topic, user_id?}` → the complete `RunArtifact`
- `GET /history?user_id=...` → that user's stored artifacts

**Part 1's asynchronous surface, retained for the streaming UI:**
- `POST /api/generate` (optional `Idempotency-Key`) → `202 {job_id}`, or `409` on key/payload mismatch
- `GET /api/jobs/{job_id}` → the live stage view
- `GET /api/jobs/{job_id}/stream` (SSE)

The synchronous endpoint does **not** run the graph in the request handler. It
submits through `services/submission.py` — the same path the asynchronous endpoint
uses — and then waits for the same worker to finish the same job. The two surfaces
therefore share the *execution*, not merely some helper code, so there is nothing
for a second implementation to drift from. The trade is that the API now depends
on a running worker, which is the dependency the async endpoint always had, made
visible to the caller as latency.
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

`cd backend && pytest` — 259 tests, no API key required. This section lists only
tests that exist; an earlier revision described an intended suite as though it
were implemented, which is exactly the kind of claim a reviewer checks.

**The three mandatory Part 2 cases** are in `test_orchestration.py` and drive the
real compiled graph with the four agents mocked, so a wrong edge fails there even
when every routing unit test passes:

1. Generator schema failure → one repair → graceful rejection
2. fail → refine → pass → approved **and tagged**
3. fail → refine → fail → refine → fail → rejected **and never tagged**

**What is covered**

| File | Covers |
|---|---|
| `test_orchestration.py` (7) | The three mandatory cases, end to end through `compiled_graph` |
| `test_orchestration_edges.py` (10) | Pass on the second refinement, a clean first draft, the enforced verdict driving the graph, failure counters (including post-call moderation), and the reviewer/tagger/moderation failure paths |
| `test_pipeline_routing.py` (16) | Routing functions **and the compiled graph's shape** — exactly two refine nodes, no backward edge, `tag` reachable only from a review |
| `test_review_schema.py` (21) | Score bounds, the documented thresholds, derived-verdict enforcement, overruling a model that claims a pass its scores do not support, existent indexed field paths, Tagger enums |
| `test_schemas.py` (13) | The Generator contract: `correct_index` bounds, four distinct position-independent options, nested explanation, required `teacher_notes`, `extra="forbid"` |
| `test_artifact.py` (14) | RunArtifact invariants (numbering, refinement chain, safety-withheld attempts, approved-implies-tagged) and the envelope round trip a follower depends on |
| `test_topic_fidelity.py` (13) | Topic reaches every prompt, delimiter escaping, no agent is invited to change the topic, thresholds are not leaked to the Reviewer, follower reuse carries the whole trail, and the live eval report accepts its full row shape |
| `test_option_order.py` (9) | Order is stable, idempotent and lossless, spreads the answer across all four positions, **and `correct_index` still points at the same answer text afterwards** |
| `test_provider_refactor.py` (11) | Provider abstraction, retry predicates, and all four agents' model/prompt cache-key coherence |
| `test_reviewer_repair.py` (6) | Bounded repair for the Reviewer and Tagger, hallucinated field paths sent back, `pass` survives the alias into the provider schema |
| `test_moderation.py` (8, parametrised over 82 topics) | Curriculum and science/PE phrasing pass, every enumerated target form is covered, plainly phrased harm requests are blocked, and **`teacher_notes` cannot bypass the output gate** |
| `test_runner_resilience.py` (5) | Deadline termination, flight-leadership loss, rollback-then-terminalize, and recovery of the complete checkpointed trail on runner failure |
| `test_canonicalize.py` (4) | Cache-key normalisation and its alias map |
| `test_history.py` (7) | `/history` is scoped to one validated user without hiding readable older artifacts; null-version terminal rows are counted; idempotency is user-bound |
| `test_rate_limit.py` (3) | Sliding-window RPM limiter |

**Reviewer evaluation set** — `tests/reviewer_golden_set.py` holds 12 hand-labelled
cases (8 fail, 4 pass), including good on-topic, coherent-but-off-topic, factual,
age-level, question-quality, distractor-quality, and topic-coverage examples. Run
`python -m tests.run_reviewer_eval` — it needs an API key and spends quota, so it
is a script rather than part of `pytest`. Read balanced accuracy and both class
recalls, not raw agreement; an always-pass or always-fail Reviewer scores only 50%
balanced accuracy.

Part 2 added a **calibration** section to that report: for the known-good cases it
prints the mean score per dimension and how many clear the required bar, plus how
often the thresholds overruled the model's own verdict. Runtime enforcement and
golden-set evaluation solve different problems and both are kept — enforcement
decides one run, the golden set decides whether the bar is set in the right place.

**A known limitation of the set**: `teacher_notes` is identical and content-free
across all twelve cases, because varying it would add a second defect signal and
confound what is being measured. Teacher-note quality is therefore unmeasured.

**Part 2 baseline (2026-08-29, `gemini-3.5-flash-lite`)**, measured across all
three reasoning budgets:

| `GEMINI_THINKING_LEVEL` | Balanced acc. | Defect recall | Good-content recall | Topic drift |
|---|---:|---:|---:|---:|
| low | 81% | 88% (7/8) | 75% (3/4) | 12/12 |
| **medium** (shipped) | **88%** | **100% (8/8)** | 75% (3/4) | 12/12 |
| high | 88% | 100% (7/7) | 75% (3/4) | 11/11 |

The reasoning budget was chosen from this table rather than from taste. At `low`
the deployed system approved a Grade 1 lesson whose quiz distractors were "a big
red truck" and "only when it rains" — answerable by elimination, which the
Reviewer's own criteria call a defect. `medium` is the only setting that catches
that case (`elimination_only_distractors`).

`high` is not merely unnecessary, it is worse: one case exhausted the Reviewer's
2048-token budget mid-reasoning and returned `finish_reason=MAX_TOKENS`, so no
judgement came back at all — which is why it is scored over 11 cases. More
reasoning inside a fixed output budget eventually crowds out the answer. That is
a concrete argument for measuring a setting instead of assuming more is better.

Thinking level is part of the cache identity (`services/cache.py`). It was not
originally, which meant changing it altered what the system produced while
content generated under the old setting kept being served.

The one remaining error at medium is over-strictness, not leniency: a
well-simplified Grade 1 gravity lesson scores 4 on correctness and the `== 5`
threshold rejects it. The thresholds overruled the model in **0/12** cases, so
the strictness lives in the scoring, not the enforcement. Four known-good cases
cannot justify moving the bar. This is a small, hand-labelled calibration
baseline rather than a production quality claim; rerun it after changing the
model, prompt, threshold, or reasoning budget.

**What is deliberately NOT covered, and why**

- **Leasing, fencing, single-flight, idempotency** have no integration tests.
  They need a live Postgres and concurrent workers; `test_runner_resilience.py`
  covers the logic paths with fakes, which is not the same thing. Treat these as
  reasoned-about rather than proven.
- **Reviewer prompt tuning.** The golden set measures; nothing tunes against it
  yet. Tuning without a baseline swings into over-rejection, which is worse than
  the leniency it would fix.
- **CI:** `.github/workflows/ci.yml` runs Ruff, compilation, all backend tests,
  the full migration chain against PostgreSQL 18.6, `alembic check`, and the
  frontend production build on every push and pull request. No LLM key is
  provided, so CI cannot spend model quota.

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
