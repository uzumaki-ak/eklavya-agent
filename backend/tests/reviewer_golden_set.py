"""Hand-labelled examples for measuring the Reviewer.

The Reviewer is the component this assignment is actually about, and it is a
model, so its quality is a measurement problem rather than something a unit test
can assert. These cases are labelled by hand with the verdict a careful teacher
would give, so its agreement rate can be checked before and after any prompt
change instead of tuning blind.

Deliberately measurement, not tuning: prompt changes made without a baseline
swing straight into over-rejection, which is a worse failure than the leniency
being fixed. Run `python -m tests.run_reviewer_eval` (needs an API key) and look
at which categories it gets wrong.

Each case: what the Reviewer is shown, and what it should say.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenCase:
    name: str
    grade: int
    topic: str
    content: dict
    expected_status: str  # "pass" | "fail"
    expected_on_topic: bool
    why: str  # what a human grader is keying on


# Cases live in their own module purely to keep both files readable.
from tests.reviewer_golden_cases import GOLDEN_SET  # noqa: E402

__all__ = ["GoldenCase", "GOLDEN_SET"]
