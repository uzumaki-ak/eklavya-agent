"""Measure the Reviewer against the hand-labelled golden set.

    python -m tests.run_reviewer_eval

Needs a real API key and spends quota (one call per case), so it is a script
rather than a pytest test — CI should not silently burn a daily allowance.

What to read from the output: raw agreement is the headline, but the per-case
table matters more. The classes are imbalanced (most real content passes), so a
Reviewer that passed everything would still score respectably on agreement while
being useless. Look specifically at whether it FAILS the cases it should fail —
that is the direction it was previously getting wrong.
"""

import asyncio
import time

from pydantic import ValidationError

from app.agents.reviewer import ReviewerAgent
from app.schemas.content import GeneratorOutput
from tests.reviewer_golden_set import GOLDEN_SET


async def _judge(agent: ReviewerAgent, case) -> tuple[str, str | None]:
    try:
        content = GeneratorOutput.model_validate(case.content)
    except ValidationError:
        # The schema rejected it before the Reviewer could see it. The system
        # still fails the case correctly, just at an earlier layer, so it counts
        # as a fail rather than an error.
        return "fail", "rejected by schema, never reached the Reviewer"

    try:
        review = await agent.run(
            content=content,
            grade=case.grade,
            topic=case.topic,
            deadline=time.monotonic() + 90,
        )
        return review.status, None
    except Exception as exc:  # a broken call is not a verdict — report it as such
        return "error", f"{type(exc).__name__}: {exc}"


async def main() -> None:
    agent = ReviewerAgent()
    rows, correct = [], 0
    should_fail = should_fail_caught = 0

    for case in GOLDEN_SET:
        status, error = await _judge(agent, case)
        ok = status == case.expected_status
        correct += ok

        if case.expected_status == "fail":
            should_fail += 1
            should_fail_caught += status == "fail"

        rows.append((case.name, case.expected_status, status, ok, error, case.why))

    print(f"\n{'case':<28} {'expected':<9} {'got':<9} ok")
    print("-" * 62)
    for name, expected, got, ok, error, _ in rows:
        print(f"{name:<28} {expected:<9} {got:<9} {'yes' if ok else 'NO'}")
        if error:
            print(f"    note: {error}")

    total = len(GOLDEN_SET)
    print(f"\nagreement: {correct}/{total} ({correct / total:.0%})")
    if should_fail:
        recall = should_fail_caught / should_fail
        print(f"recall on cases that SHOULD fail: {should_fail_caught}/{should_fail} ({recall:.0%})")
        print("  ^ the number that matters — leniency shows up here, not in agreement")

    misses = [(n, w) for n, _, _, ok, _, w in rows if not ok]
    if misses:
        print("\nmissed:")
        for name, why in misses:
            print(f"  {name}: {why}")


if __name__ == "__main__":
    asyncio.run(main())
