## Context — verifying the fixes you advised on

You reviewed commit `0ecbbbb`, found follow-up defects, and those fixes are now in
the working tree but deliberately uncommitted. **Verify the diff — do not take
this summary at face value, do not commit or push, and do not re-argue scope.**

Same evidence bar as previous rounds: cite file and line, check claims against
code rather than documentation, and say explicitly when you cannot confirm
something.

### Your four plan changes — all adopted

1. **Failing tests first, docs last.** The moderation failure was reproduced
   before the fix (3 curriculum topics wrongly blocked, 6 harmful requests wrongly
   allowed — 9 failures), then fixed to 0. Docs were corrected only after all
   behaviour was final.
2. **No keyword matching for topic fidelity.** Implemented exactly as you
   specified: `ReviewerJudgement` carries `addresses_requested_topic: bool`, a
   Pydantic `model_validator` forces `status="fail"` when it is false, and
   `to_output()` projects to the spec's `{status, feedback}` shape. No third LLM
   call.
3. **Off-topic is a content failure.** It resolves to `completed_fail` through the
   normal review path, not `generator_error`.
4. **Measure, do not tune.** The evaluation set holds 12 hand-labelled cases
   (8 fail, 4 pass), including both live misses. It reports a confusion matrix,
   both class recalls, balanced accuracy, and topic-flag accuracy. Schema-rejected
   cases are skipped rather than credited to the Reviewer. No live eval has run.

### Your six additional findings — all addressed

- **`refinement_count` reuse** — `STAGE_FIELDS` now drives Redis, direct cache,
  persistence, and `single_flight.copy_result`; the actual follower function has
  a regression test.
- **Cache identity** — `moderation_policy_version=v3`, `schema_version=v6`, and
  both prompt versions are `v5`; canonicalizer remains `v1`.
- **`ReviewCard` promising a rewrite that never comes** — copy is now
  first/final aware; a failed final says "not approved", not "gets rewritten".
- **Failed final rewrite still had a playable quiz** — `App.jsx` now passes
  `superseded={job.final_review?.status === "fail"}`, and `ContentCard`'s
  rejected-note and expand-label are per-variant.
- **Topic as untrusted input** — delimiter characters are neutralised by
  `escape_topic()` before both Generator and Reviewer prompt interpolation.
- **Title only after fidelity is enforced** — the refined card now gets
  `title={job.topic}`, added in the same change as the fidelity enforcement.

### Also changed

- `moderation.py` uses direct action/object grammar, passive/instruction patterns,
  and a self-harm-only help override. It remains explicitly demo-grade regex.
- `ARCHITECTURE.md`: constants corrected to match `config.py` (120/150/2), the
  never-implemented per-IP rate-limiting claim replaced with an explicit statement
  that no HTTP throttling exists, the graph diagram corrected (moderation is
  inlined in the generate/refine nodes, not separate graph nodes), and the Testing
  section rewritten to list only tests that run.
- Test count is 140, all passing. Frontend builds; no source file exceeds 200 lines.

---

## What I want you to check

1. **Does `addresses_requested_topic` fail closed?** It is required in the JSON
   schema. Confirm omission raises validation, validator ordering remains sound,
   and `to_output()` cannot leak the internal field. Do not overclaim independent
   drift detection: the validator enforces the model's self-report only.

2. **Is the moderation rewrite genuinely better, or differently broken?** Try to
   find both a legitimate school topic it still blocks and a harmful request it
   still allows. I expect obfuscated requests get through — I want to know if
   anything *plainly phrased* does.

3. **The `STAGE_FIELDS` change touches every envelope consumer.** Confirm nothing
   else breaks: `cache.py` get/set, `persist_reused`, `persist_result`, the direct
   API cache path in `generate.py`, and `write_stage`'s column mapping.

4. **Does the 12-case golden set discriminate?** Confirm always-pass and
   always-fail both score 50% balanced accuracy, schema-invalid cases are skipped,
   topic flags are scored, and the modules import without order dependence.

5. **Prompt-version bumps** — are all the versions that needed bumping actually
   bumped, and is `canonicalizer_version` correctly left alone?

6. **Anything the fixes broke.** Especially the frontend: `ContentCard` now takes
   per-variant copy and the final card can be `superseded`; check the collapse
   behaviour and the `useEffect` interaction still make sense for both variants.

7. **Anything still wrong that none of us has caught.**

Opinion and verification only — no edits.
