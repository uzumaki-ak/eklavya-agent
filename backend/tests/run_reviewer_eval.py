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
"""

import asyncio
import time

from pydantic import ValidationError

from app.agents.reviewer import ReviewerAgent
from app.schemas.content import GeneratorOutput
from tests.reviewer_golden_set import GOLDEN_SET

SKIPPED = "skipped"


async def _judge(agent: ReviewerAgent, case) -> tuple[str, bool | None, str | None]:
    """Returns (status, on_topic, note). Status may be 'skipped' or 'error'."""
    try:
        content = GeneratorOutput.model_validate(case.content)
    except ValidationError:
        # The schema rejected it before the Reviewer ran. The system handles the
        # case correctly, but the Reviewer was never tested — counting it as a
        # Reviewer success would inflate the score for work it did not do.
        return SKIPPED, None, "rejected by schema; the Reviewer never saw it"

    try:
        judgement = await agent.judge(
            content=content, grade=case.grade, topic=case.topic,
            deadline=time.monotonic() + 90,
        )
        return judgement.status, judgement.addresses_requested_topic, None
    except Exception as exc:
        return "error", None, f"{type(exc).__name__}: {exc}"


def _report(rows: list[tuple]) -> None:
    metrics = _classification_metrics(rows)
    tp, fn = metrics["tp"], metrics["fn"]
    tn, fp = metrics["tn"], metrics["fp"]

    print(f"\n{'case':<30} {'expected':<9} {'got':<9} {'on-topic':<9} ok")
    print("-" * 72)
    for name, expected, got, on_topic, ok, note, _ in rows:
        flag = "-" if on_topic is None else ("yes" if on_topic else "NO")
        print(f"{name:<30} {expected:<9} {got:<9} {flag:<9} {'yes' if ok else 'NO'}")
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
    tp = sum(1 for r in scored if r[1] == "fail" and r[2] == "fail")
    fn = sum(1 for r in scored if r[1] == "fail" and r[2] == "pass")
    tn = sum(1 for r in scored if r[1] == "pass" and r[2] == "pass")
    fp = sum(1 for r in scored if r[1] == "pass" and r[2] == "fail")
    fail_recall = tp / (tp + fn) if (tp + fn) else 0.0
    pass_recall = tn / (tn + fp) if (tn + fp) else 0.0
    return {
        "tp": tp, "fn": fn, "tn": tn, "fp": fp,
        "fail_recall": fail_recall,
        "pass_recall": pass_recall,
        "balanced_accuracy": (fail_recall + pass_recall) / 2,
    }


async def main() -> None:
    agent = ReviewerAgent()
    rows = []
    for case in GOLDEN_SET:
        status, on_topic, note = await _judge(agent, case)
        ok = status == case.expected_status
        rows.append(
            (case.name, case.expected_status, status, on_topic, ok, note, case.expected_on_topic)
        )
    _report(rows)


if __name__ == "__main__":
    asyncio.run(main())
