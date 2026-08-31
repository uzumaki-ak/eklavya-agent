"""Measure the Reviewer against the hand-labelled golden set.

    python -m tests.run_reviewer_eval

Needs a real API key and spends quota (one call per case), so it is a script
rather than a pytest test — CI should not silently burn a daily allowance.

READ THE BALANCED ACCURACY, NOT THE AGREEMENT. The set is deliberately
fail-heavy (most defects are more interesting than most correct lessons), so a
Reviewer that simply failed everything would still score well on raw agreement
and 100% fail recall while being completely useless. Balanced accuracy — the mean of fail
recall and pass recall — is the number that cannot be gamed that way, and the
confusion matrix shows which direction any error runs in.

`addresses_requested_topic` is scored separately: a Reviewer can reach the right
verdict for the wrong reason, and topic drift is the failure this whole mechanism
exists to catch.

Part 2 added the score calibration section. The verdict is derived from
thresholds in `app.schemas.review.PASS_THRESHOLDS`, and a threshold is only as
good as the distribution it sits in: if known-good lessons rarely score 5 on
correctness, requiring 5 rejects good content rather than catching bad content.
The report prints that distribution so the bar can be set from evidence.
"""

import asyncio
import time

from pydantic import ValidationError

from app.agents.execution import ExecutionContext
from app.agents.reviewer import ReviewerAgent
from app.schemas.review import PASS_THRESHOLDS
from app.schemas.content import GeneratorOutput
from tests.reviewer_golden_set import GOLDEN_SET

SKIPPED = "skipped"


async def _judge(agent: ReviewerAgent, case):
    """Returns (verdict, on_topic, note, judgement).

    `verdict` is a bool, or the string 'skipped'/'error' when the case was not
    scored.
    """
    try:
        content = GeneratorOutput.model_validate(case.content)
    except ValidationError:
        # The schema rejected it before the Reviewer ran. The system handles the
        # case correctly, but the Reviewer was never tested — counting it as a
        # Reviewer success would inflate the score for work it did not do.
        return SKIPPED, None, "rejected by schema; the Reviewer never saw it", None

    try:
        judgement = await agent.judge(
            content=content,
            grade=case.grade,
            topic=case.topic,
            ctx=ExecutionContext(deadline=time.monotonic() + 90),
        )
        return judgement.passed, judgement.addresses_requested_topic, None, judgement
    except Exception as exc:
        return "error", None, f"{type(exc).__name__}: {exc}", None


def _report(rows: list[tuple]) -> None:
    metrics = _classification_metrics(rows)
    tp, fn = metrics["tp"], metrics["fn"]
    tn, fp = metrics["tn"], metrics["fp"]

    print(f"\n{'case':<30} {'expected':<9} {'got':<9} {'on-topic':<9} ok")
    print("-" * 72)
    for name, expected, got, on_topic, ok, note, _expected_on_topic, _judgement in rows:
        flag = "-" if on_topic is None else ("yes" if on_topic else "NO")
        print(
            f"{name:<30} {_verdict(expected):<9} {_verdict(got):<9} "
            f"{flag:<9} {'yes' if ok else 'NO'}"
        )
        if note:
            print(f"    note: {note}")

    print("\nconfusion matrix (scored cases only)")
    print(f"  caught a real defect      {tp}")
    print(f"  MISSED a real defect      {fn}   <- leniency")
    print(f"  left good content alone   {tn}")
    print(f"  REJECTED good content     {fp}   <- over-strictness")

    fail_recall = metrics["fail_recall"]
    pass_recall = metrics["pass_recall"]
    balanced = metrics["balanced_accuracy"]

    print(f"\n  fail recall      {fail_recall:.0%}   (of defects, how many caught)")
    print(f"  pass recall      {pass_recall:.0%}   (of good lessons, how many left alone)")
    print(f"  BALANCED ACC     {balanced:.0%}   <- the headline; 50% = no better than always-one-answer")

    on_topic_cases = [r for r in rows if r[3] is not None]
    if on_topic_cases:
        correct = sum(1 for r in on_topic_cases if r[3] == r[6])
        print(f"\n  topic-drift flag {correct}/{len(on_topic_cases)} correct")

    skipped = [r for r in rows if r[2] in (SKIPPED, "error")]
    if skipped:
        print(f"\n  {len(skipped)} case(s) not scored: " + ", ".join(r[0] for r in skipped))


def _classification_metrics(rows: list[tuple]) -> dict[str, float | int]:
    """Pure metric calculation, kept separate so degenerate baselines are testable."""
    scored = [r for r in rows if r[2] not in (SKIPPED, "error")]
    tp = sum(1 for r in scored if r[1] is False and r[2] is False)
    fn = sum(1 for r in scored if r[1] is False and r[2] is True)
    tn = sum(1 for r in scored if r[1] is True and r[2] is True)
    fp = sum(1 for r in scored if r[1] is True and r[2] is False)
    fail_recall = tp / (tp + fn) if (tp + fn) else 0.0
    pass_recall = tn / (tn + fp) if (tn + fp) else 0.0
    return {
        "tp": tp, "fn": fn, "tn": tn, "fp": fp,
        "fail_recall": fail_recall,
        "pass_recall": pass_recall,
        "balanced_accuracy": (fail_recall + pass_recall) / 2,
    }


def _verdict(value) -> str:
    """Render a bool verdict, or pass through 'skipped'/'error'."""
    if value is True:
        return "pass"
    if value is False:
        return "fail"
    return str(value)


def _calibration(rows: list[tuple]) -> None:
    """Are the thresholds set where the scores actually fall?

    A threshold that almost no good lesson clears is miscalibrated, not strict.
    """
    judged = [r for r in rows if len(r) > 7 and r[7] is not None]
    if not judged:
        return

    print("\nscore calibration (known-good cases only)")
    good = [r[7] for r in judged if r[1] is True]
    if not good:
        print("  no pass-labelled cases were scored")
    else:
        for name, floor in sorted(PASS_THRESHOLDS.items()):
            values = [getattr(j.scores, name) for j in good]
            clearing = sum(1 for v in values if v >= floor)
            mean = sum(values) / len(values)
            print(
                f"  {name:<20} mean {mean:.1f}   {clearing}/{len(values)} clear "
                f"the required {floor}"
            )
        print("  a dimension few good lessons clear is a miscalibrated bar, not a strict one")

    overruled = sum(1 for j in (r[7] for r in judged) if j.overruled)
    print(f"\n  verdict overruled by the thresholds in {overruled}/{len(judged)} case(s)")


async def main() -> None:
    agent = ReviewerAgent()
    rows = []
    for case in GOLDEN_SET:
        verdict, on_topic, note, judgement = await _judge(agent, case)
        ok = verdict == case.expected_pass
        rows.append(
            (
                case.name, case.expected_pass, verdict, on_topic, ok, note,
                case.expected_on_topic, judgement,
            )
        )
    _report(rows)
    _calibration(rows)


if __name__ == "__main__":
    asyncio.run(main())
