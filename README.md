# Eklavya — Governed, Auditable AI Content Pipeline

Four agents produce grade-appropriate lessons behind a quantitative quality gate,
and every run leaves a complete audit trail from first draft to final decision.

**Live:** <https://sincere-perfection-production-95aa.up.railway.app>

Design rationale and revision history: [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Agent roles

| Agent | Input | Output | Responsibility |
|---|---|---|---|
| **Generator** | `{grade, topic}` | `explanation`, `mcqs`, `teacher_notes` | Write the draft |
| **Reviewer** | the draft (+ grade, topic) | four 1–5 `scores`, `pass`, field-anchored `feedback` | Judge it |
| **Refiner** | draft + feedback | a corrected draft | Fix exactly what was criticised |
| **Tagger** | **approved** content | `subject`, `topic`, `grade`, `difficulty`, `content_type`, `blooms_level` | Classify it |

The Refiner is a separate agent rather than the Generator with extra text
appended. The two have different inputs and different failure modes: the
Generator invents from a topic, the Refiner repairs a specific artifact against a
specific list of complaints. Part 1 conflated them, and the result was
refinements that rewrote from scratch and lost what the Reviewer had accepted.

The Tagger runs on approved content only, and that is enforced by the graph — the
tag node has no inbound edge except from a passing review.

---

## Pass/fail criteria

The Reviewer returns a `pass` boolean, and **the pipeline ignores it**. The
verdict is recomputed in code from the scores and the outstanding feedback:

```
pass  ⟺  every score clears its threshold
         ∧ no feedback items remain
         ∧ the lesson addresses the requested topic
```

| Dimension | Minimum to pass |
|---|---:|
| `correctness` | **5** |
| `age_appropriateness` | 4 |
| `clarity` | 4 |
| `coverage` | 4 |

Correctness is the one dimension with no tolerance: a lesson that is 80%
factually right is not 80% acceptable to put in front of a child. The other three
are matters of degree where a judge model's 4-versus-5 distinction is mostly
noise, so a 4 passes.

Two consequences worth stating plainly:

- **A model cannot approve content its own scores condemn.** Returning
  `pass: true` next to `correctness: 2` is a thing judge models really do; here
  it is overruled and logged.
- **Every failure is explained.** A score below its threshold synthesises a
  feedback item naming the dimension, so a rejection always arrives with
  something the Refiner can act on. Feedback that names a field which does not
  exist (`"the second paragraph"`) fails validation and goes back to the model.

The Reviewer is **not told the thresholds**. A model told "correctness must be 5
to pass" learns to return 5. Scoring honestly is its job; deciding what clears
the bar is the pipeline's. Thresholds live in `app/schemas/review.py`.

Calibration matters as much as the numbers: `python -m tests.run_reviewer_eval`
prints, for the known-good cases in the golden set, how many actually clear each
bar. A threshold few good lessons reach is miscalibrated, not strict.

### Reviewer evaluation baseline

Measured on **2026-08-29**, `gemini-3.5-flash-lite`, 12 hand-labelled cases:

| `GEMINI_THINKING_LEVEL` | Balanced acc. | Defect recall | Good-content recall | Topic drift |
|---|---:|---:|---:|---:|
| low | 81% | 88% (7/8) | 75% (3/4) | 12/12 |
| **medium** (shipped) | **88%** | **100% (8/8)** | 75% (3/4) | 12/12 |
| high | 88% | 100% (7/7) | 75% (3/4) | 11/11 |

Medium is the shipped setting because it is the only one that catches
`elimination_only_distractors` — a quiz whose wrong options are absurd enough to
be answerable by elimination. That case was not academic: at `low` the live
system approved a Grade 1 lesson whose distractors were "a big red truck" and
"only when it rains".

High buys nothing and costs reliability: one case exhausted the Reviewer's
2048-token budget mid-reasoning and returned `finish_reason=MAX_TOKENS`, so no
judgement came back at all. It is scored over 11 cases rather than 12 for that
reason.

The one remaining error at medium is over-strictness, not leniency: a
well-simplified Grade 1 gravity lesson scores 4 on correctness and is rejected by
the `== 5` threshold. Note `verdict overruled by the thresholds in 0/12 cases` —
the model's own judgement agreed with the derived verdict every time, so the
strictness is in the scoring, not in the enforcement. Four known-good cases is
too small a sample to move the bar on; it is recorded rather than tuned against.

---

## Orchestration

```
moderate ─► generate ─► review_1 ─┬─ pass ──────────────────────────► tag ─► approved
                                  └─ fail ─► refine_1 ─► review_2 ─┬─ pass ─► tag
                                                                   └─ fail ─►
            refine_2 ─► review_3 ─┬─ pass ─► tag ─► approved
                                  └─ fail ──────────► rejected
```

**The two-refinement cap is structural, not counted.** The graph is unrolled and
acyclic: there are exactly two refine nodes, `refine_2` is reachable only from
`review_2`, and `review_3` has no edge to any refinement. A third refinement is
not something the graph can express. A counted loop would push the same guarantee
into a comparison that a later edit can get wrong; `test_pipeline_routing.py`
asserts the shape itself, not just the routing functions.

**Bounded budgets**, kept separate because they fail for different reasons:

| Budget | Limit | Why separate |
|---|---:|---|
| Refinements | 2 | Content quality — needs new feedback |
| Schema repairs | 1 per agent | The model got it wrong — feed the error back |
| Transport retries | 2 | The call never landed — repeat it unchanged |

Merging the last two would let a network blip consume the model's one chance to
correct itself. The repair budget is the spec's: *"If validation fails → retry
once, then fail gracefully."*

---

## The RunArtifact

`POST /generate` returns one object covering the whole lifecycle: the input,
every `attempt` as a `{attempt, draft, review, refined}` cycle, the final
approved/rejected decision with content and tags, timestamps, and provenance
(models, prompt versions, retry counts, cache hit).

If output moderation stops an attempt, its text is not retained: that cycle has
`draft: null` and `content_withheld: true`, while `moderation_results`, counters
and refinement count record what happened.

It is the source of truth. The four Part 1 columns on `generation_runs` remain as
a fixed-width summary for the live UI and for indexing, but both they and the
artifact are projections of **one** envelope — see `app/services/envelope.py`.
Part 1 had two paths derive a run's status independently and they disagreed; one
derivation is the fix.

Structural invariants are enforced by the schema, not trusted from the pipeline:
attempts must be numbered consecutively, each attempt's refinement must be the
next attempt's draft, approved runs must carry content and tags, and rejected
runs must not carry tags.

---

## API

**Required surface** (unprefixed, exactly as specified):

```
POST /generate               {grade, topic, user_id?}  →  RunArtifact
GET  /history?user_id=...                              →  stored RunArtifacts
```

**Part 1's asynchronous surface**, kept for the streaming UI:

```
POST /api/generate           →  202 {job_id}
GET  /api/jobs/{id}          →  live stage view
GET  /api/jobs/{id}/stream   →  SSE
```

`POST /generate` is synchronous to the caller but does not run the graph in the
request handler. It submits through the same path as the asynchronous endpoint
and waits for the same worker, so the two surfaces cannot drift — there is one
pipeline and this is a facade over it. The cost is that the API depends on a
running worker, visible to the caller as latency.

`user_id` may also arrive as an `X-User-Id` header; with neither, the run is
attributed to the anonymous session. An IP-derived session is not a user, so
`/history` never keys off one.

---

## Quick start

```bash
cp .env.example .env          # add your GEMINI_API_KEY
docker compose up --build
```

Open <http://localhost:3000>. The API is not published to the host — the frontend
container reverse-proxies `/api`, so everything is same-origin.

```bash
curl -s localhost:3000/generate -H 'content-type: application/json' \
  -d '{"grade":5,"topic":"Fractions as parts of a whole","user_id":"demo"}'
curl -s 'localhost:3000/history?user_id=demo'
```

---

## Testing

```bash
cd backend && pip install -e ".[dev]" && pytest
```

259 tests, no API key required. The three mandatory orchestration cases are in
`tests/test_orchestration.py` and drive the real compiled graph with the agents
mocked, so a wrong edge fails even when every unit test passes.

GitHub Actions runs Ruff, compilation, all backend tests, the full PostgreSQL
migration chain plus `alembic check`, and the frontend production build on every
push and pull request. It uses no LLM key and therefore cannot spend model quota.

## Trade-offs

- **A tagging failure rejects the run.** The artifact's contract is that approved
  content is catalogued, so publishing an untagged approval would break it.
  `final.pipeline_status` keeps it distinguishable from a quality rejection. The
  cost is that a good lesson can be rejected by a classifier hiccup.
- **Requiring `correctness: 5` will reject some good content.** Deliberate for
  this audience, and the reason the eval harness reports the score distribution
  rather than only the verdict.
- **The synchronous endpoint needs a worker.** It buys one execution path instead
  of two; it costs an extra moving part in the request's dependency chain.
- **Pre-Part-2 rows without artifacts cannot be reconstructed.** `/history`
  reports their count. Artifacts that do exist are validated and returned across
  schema-version bumps; genuinely incompatible payloads are counted rather than
  crashing the entire history response.
- **Moderation matches word proximity, not meaning.** Euphemistic harm can get
  through and unusual legitimate phrasing can be blocked. It is a demo-grade
  pre-filter; a hosted classifier belongs here before real children use this.
- **Safety-blocked model text is withheld from the artifact.** The attempt,
  refinement count, call counters and structured moderation outcome remain in
  the audit trail, but the blocked text itself is not stored or returned by
  `/history`. This preserves accountability without retaining harmful content.
- **`LLM_REQUESTS_PER_MINUTE` is process-local.** Horizontal scaling needs a
  distributed limiter or reliance on the provider's own quota.
