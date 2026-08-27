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

# The type and cases share one dependency-free module. Keeping a dataclass here
# and importing the cases back created a circular import that worked only when
# this module happened to be imported first.
from tests.reviewer_golden_cases import GOLDEN_SET, GoldenCase

__all__ = ["GoldenCase", "GOLDEN_SET"]
