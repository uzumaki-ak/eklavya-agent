"""Reviewer I/O schemas — quantitative scoring with an enforced verdict.

The Part 2 contract asks the Reviewer for four 1-5 scores, a boolean `pass`, and
field-referenced feedback. The important design decision is that **`pass` is
derived, never trusted**: the model reports scores and problems, and code decides
the verdict from documented thresholds.

That matters because a judge model will happily return `pass: true` next to a
correctness score of 2, or attach three complaints to a verdict of "pass".
Part 1 already had to overrule exactly that behaviour for topic drift; making the
whole verdict a pure function of the scores and the feedback generalises it.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Documented pass thresholds (README "Pass/fail criteria"). Correctness is the
# one dimension with no tolerance: a lesson that is 80% factually right is not
# 80% acceptable to put in front of a child. The other three allow a 4, because
# they are matters of degree where a judge model's 4-vs-5 distinction is noise.
PASS_THRESHOLDS: dict[str, int] = {
    "correctness": 5,
    "age_appropriateness": 4,
    "clarity": 4,
    "coverage": 4,
}

TOPIC_DRIFT_ISSUE = (
    "This lesson does not teach the topic that was requested. "
    "Rewrite it so it teaches the requested topic at this grade level."
)

# Field paths the Reviewer is allowed to cite. Anything else is a hallucinated
# location, which makes the feedback unactionable for the Refiner — so it fails
# validation and goes back to the model rather than into the audit trail.
_FIELD_PATH_RE = re.compile(
    r"^(?:"
    r"explanation\.(?:text|grade)"
    r"|teacher_notes\.(?:learning_objective|common_misconceptions(?:\[\d+\])?)"
    r"|mcqs\[\d+\](?:\.(?:question|correct_index|options(?:\[\d+\])?))?"
    r")$"
)

ScoreName = Literal["age_appropriateness", "correctness", "clarity", "coverage"]


class ReviewScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_appropriateness: int = Field(ge=1, le=5)
    correctness: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    coverage: int = Field(ge=1, le=5)

    def failing_dimensions(self) -> list[str]:
        """Which scores sit below their documented threshold, in a stable order."""
        return [
            name for name, floor in PASS_THRESHOLDS.items() if getattr(self, name) < floor
        ]


class ReviewFeedback(BaseModel):
    """One problem, anchored to the field it is about."""

    model_config = ConfigDict(extra="forbid")

    field: str
    issue: str

    @model_validator(mode="after")
    def check_path_and_issue(self):
        path = self.field.strip()
        if not _FIELD_PATH_RE.match(path):
            raise ValueError(
                f"field must be a real content path such as 'explanation.text', "
                f"'teacher_notes.learning_objective' or 'mcqs[0].options[2]'; got {path!r}"
            )
        self.field = path
        if not self.issue.strip():
            raise ValueError("issue must not be blank")
        self.issue = self.issue.strip()
        return self


class ReviewerOutput(BaseModel):
    """The public, spec-shaped review: {scores, pass, feedback}.

    `pass` is a Python keyword, so the attribute is `passed` and the wire name is
    restored by the alias. Always dump this model with `by_alias=True`.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    scores: ReviewScores
    passed: bool = Field(alias="pass")
    feedback: list[ReviewFeedback] = Field(default_factory=list)

    @model_validator(mode="after")
    def fail_must_explain(self):
        if not self.passed and not self.feedback:
            raise ValueError("a failing review must include at least one feedback item")
        if self.passed and self.feedback:
            raise ValueError("a passing review must not carry unresolved feedback")
        return self


class ReviewerJudgement(BaseModel):
    """What the Reviewer model actually answers into.

    Carries one extra internal field (`addresses_requested_topic`) that the
    public shape hides. Both it and the reported `pass` are inputs to the
    verdict, not the verdict itself — see `enforce_verdict` below.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    scores: ReviewScores
    # Required in the provider schema, with no default. A default would fail
    # OPEN: an omitted field would read as "the model approved it".
    reported_pass: bool = Field(alias="pass")
    feedback: list[ReviewFeedback]
    # Required for the same reason. A model that notices the lesson is off-topic
    # but still answers "pass" (a Grade 1 quantum entanglement request came back
    # as an approved lesson about solids and liquids) is overruled below.
    addresses_requested_topic: bool

    @model_validator(mode="after")
    def enforce_verdict(self):
        """Make every failure explainable, so the verdict follows from the feedback."""
        if not self.addresses_requested_topic and not self._mentions(TOPIC_DRIFT_ISSUE):
            self.feedback = [
                ReviewFeedback(field="explanation.text", issue=TOPIC_DRIFT_ISSUE),
                *self.feedback,
            ]

        for name in self.scores.failing_dimensions():
            score = getattr(self.scores, name)
            marker = f"scored {score}/5 on {name}"
            if not self._mentions(marker):
                self.feedback = [
                    *self.feedback,
                    ReviewFeedback(
                        field="explanation.text",
                        issue=(
                            f"This draft {marker}, below the required minimum of "
                            f"{PASS_THRESHOLDS[name]}. Revise until it clears that bar."
                        ),
                    ),
                ]
        return self

    def _mentions(self, needle: str) -> bool:
        return any(needle in item.issue for item in self.feedback)

    @property
    def passed(self) -> bool:
        """The enforced verdict: thresholds met, on topic, and nothing outstanding."""
        return not self.feedback and not self.scores.failing_dimensions()

    @property
    def overruled(self) -> bool:
        """True when the model's own `pass` disagreed with the enforced verdict."""
        return self.reported_pass != self.passed

    def to_output(self) -> ReviewerOutput:
        return ReviewerOutput(
            scores=self.scores, passed=self.passed, feedback=list(self.feedback)
        )
