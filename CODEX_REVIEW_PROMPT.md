## Context — a second opinion on a fix plan, before any code is written

You have reviewed this codebase across several rounds already. It is now deployed and working. An independent evaluator then rated it against the original assignment and found real defects. I have a proposed fix plan. **I want your opinion on the plan before I implement it — do not write code, do not edit files.**

Read `ARCHITECTURE.md` and the relevant source, then push back where you disagree.

### One thing that is NOT up for discussion

The evaluator's largest criticism was scope: the brief said *"you do not need a full agent framework — simple Python classes or functions are sufficient"*, and this submission ships a queue, worker, DB leasing with fencing, single-flight election, caching, rate limiting and a provider abstraction. **The author has considered that and is deliberately keeping it.** Do not spend your review re-arguing it or recommending deletion. Assume the architecture stays as-is and evaluate the fixes within it.

---

## The defects found

**1. Moderation is inverted, not merely weak.** `app/services/moderation.py` uses a regex pre-filter. Verified live:

| Topic | Result |
|---|---|
| "sexual reproduction in plants" | **blocked** |
| "why drugs are harmful to the body" | **blocked** |
| "sexism in the workplace" | **blocked** |
| "how to make a bomb at home" | allowed |
| "ways to hurt yourself" | allowed |

`\b(bomb|explosive|firearm|weapon)\s*(making|building|how to)` requires the verb *after* the noun, so it matches almost no natural phrasing. `ARCHITECTURE.md` discloses this as "demo-grade", which covers weak but arguably not inverted. Audience is school-age children.

**2. The Reviewer is never told the topic.** Confirmed: `REVIEWER_USER` in `app/agents/prompts.py` interpolates only `{grade}` and `{content}`; the string `topic` does not appear in `app/agents/reviewer.py`. Consequences:
- Reviewer criterion 4 ("Coverage — does the explanation teach the essential idea requested by the topic?") is structurally unevaluable.
- Nothing anywhere asserts that `refined_output` is still about the requested topic.
- The Reviewer's prompt does not stop it from rejecting the *request* rather than critiquing the *draft*. Live example: Grade 1 / "quantum entanglement" → Reviewer says *"Please replace the topic with age-appropriate 1st-grade science content"* → Generator writes a lesson on solids/liquids/gases → second review returns `pass` → UI shows "Checked and approved", page still headed "quantum entanglement". A child asked one question and got a confident green-ticked answer to a different one.

Note the author already solved this exact class of problem for *grade* (injected as prompt context, documented in ARCHITECTURE.md because the spec's Reviewer input is content-only) and missed the identical gap for topic.

**3. `refinement_count` is always 0 on cache hits.** It is not in `STAGE_FIELDS`, so `persist_reused` never writes it — cache hits and single-flight followers report 0 even with `refined_output` and `final_review` present. The README promises complete envelopes on cache hits.

**4. `ARCHITECTURE.md` claims things that are not true.** Its Testing section, under a heading saying IMPLEMENTED, lists fencing, lease-cancellation, single-flight, idempotency, golden-set and moderation tests. None exist. It also carries stale constants (240s/300s/4 attempts vs the shipped 120/150/2), draws `moderate_output` as graph nodes when it is inlined in `generate_original_node`/`refine_node`, and claims per-IP rate limiting that does not exist.

**5. Reviewer calibration.** It passes questions answerable by pure elimination ("A warm cozy blanket" as a black-hole distractor) despite its own criterion 6 telling it to fail exactly that. Distinct from #2: here it has the information and does not apply it.

---

## The proposed plan

1. **Rewrite the moderation filter** so it stops blocking legitimate curriculum topics and starts catching the phrasings it currently misses. Keep it local/regex (no new external dependency), but built from higher-precision patterns with intent context rather than bare nouns.
2. **Pass the topic to the Reviewer**, so criterion 4 can actually fire.
3. **Constrain the Reviewer to critiquing the draft**, never to rejecting or substituting the requested topic. If a topic genuinely cannot be taught at that grade, that should surface honestly to the user rather than becoming a silent swap.
4. **Add a topic-fidelity check** so a refinement cannot change the subject — a run that drifts should fail visibly rather than complete with a green tick.
5. **Fix `refinement_count`** on the reused-envelope path, and give the refined card a title so the page does not read as though the refined lesson answers the original heading.
6. **Write the missing tests**, prioritising moderation and the Reviewer — the two components with zero coverage and the two the assignment is actually about.
7. **Correct `ARCHITECTURE.md`** so every claim matches the code: fix the constants, the diagram, remove the rate-limiting claim, and make the Testing section describe only tests that exist.
8. **Deliberately deferred:** deep Reviewer calibration for distractor quality (#5). The reasoning is that tuning it without a hand-labelled golden set risks swinging into over-rejection, which is a worse failure than the current leniency, and #2 already removes the largest miss.

---

## What I want from you

1. **Is the plan right?** Anything mis-prioritised, anything that will not actually fix the defect it targets.
2. **Item 1 specifically** — is a hardened regex defensible for a child-facing product, or is the honest answer that only a hosted classifier will do and anything else is theatre? Say so if so.
3. **Item 4 specifically** — how would you implement a topic-fidelity check without it becoming a third LLM call or a brittle keyword match? Is failing the run the right outcome, or is there a better one?
4. **Item 8** — do you agree calibration should be deferred, or is shipping a Reviewer that demonstrably ignores its own criterion 6 worse than the over-rejection risk?
5. **Anything the evaluator and I both missed.** You know this codebase; the evaluator saw it fresh. Assume there are defects neither of us named.
6. Flag any fix that would **break something currently working**.

Same evidence bar as previous rounds: cite file and line, verify claims against code rather than documentation, and say explicitly when you cannot confirm something. Opinion and reasoning only — no edits.
