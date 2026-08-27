"""Agent I/O schemas — the exact contract from the assessment spec.

Shape is enforced by each provider's native structured output; the cross-field rules
below (answer-in-options, uniqueness) are Python-level and raise ValidationError,
which is why the generator needs a separate schema-repair loop.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_RELATIVE_OPTION_RE = re.compile(
    r"\b(?:all|none|both|either|neither)\s+of\s+(?:the\s+)?"
    r"(?:(?:options?|choices?|answers?)\s+)?(?:above|below)\b"
    r"|\b(?:first|second|third|fourth|last)(?:\s+(?:two|three))?\s+"
    r"(?:options?|choices?|answers?)\b",
    re.IGNORECASE,
)
_OPTION_LABEL_EXPRESSION_RE = re.compile(
    r"^(?:(?:both|either|neither)\s+)?"
    r"(?:(?:options?|choices?|answers?)\s+)?[A-D1-4]\s*"
    r"(?:and|or|nor|&)\s*"
    r"(?:(?:options?|choices?|answers?)\s+)?[A-D1-4]$",
    re.IGNORECASE,
)
_OPTION_LABEL_PREFIX_RE = re.compile(r"^[A-D]\s*[.):\-]\s+", re.IGNORECASE)


def _depends_on_option_position(option: str) -> bool:
    """Return whether reordering would change or mislabel this option's meaning."""
    value = option.strip()
    return any(
        pattern.search(value)
        for pattern in (
            _RELATIVE_OPTION_RE,
            _OPTION_LABEL_EXPRESSION_RE,
            _OPTION_LABEL_PREFIX_RE,
        )
    )


class MCQ(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    # A bounded list maps to the portable JSON Schema minItems/maxItems shape.
    # A fixed Python tuple emits prefixItems, which Gemini Generate Content's
    # current SDK schema converter rejects before making the API call.
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
    def check_options_and_answer(self):
        normalized = [o.strip() for o in self.options]
        if any(not o for o in normalized):
            raise ValueError("options must not be blank")
        if any(_depends_on_option_position(o) for o in normalized):
            raise ValueError(
                "options must not depend on positions or labels such as "
                "'all of the above', 'both A and B', or 'the first option'"
            )
        if len(set(normalized)) != 4:
            raise ValueError("options must be four distinct strings")
        if self.answer.strip() not in normalized:
            raise ValueError("answer must exactly match one of the four options")
        return self


class GeneratorInput(BaseModel):
    """Spec input: {"grade": 4, "topic": "Types of angles"}"""

    model_config = ConfigDict(extra="forbid")

    grade: int = Field(ge=1, le=12)
    topic: str = Field(min_length=1, max_length=200)


class GeneratorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanation: str
    mcqs: list[MCQ] = Field(min_length=1, max_length=10)

    @field_validator("explanation")
    @classmethod
    def explanation_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("explanation must not be blank")
        return v


TOPIC_DRIFT_FEEDBACK = (
    "This lesson does not teach the topic that was requested. "
    "Rewrite it so it teaches the requested topic at this grade level."
)


class ReviewerJudgement(BaseModel):
    """What the Reviewer model actually returns.

    `addresses_requested_topic` makes the Reviewer's coverage judgement
    enforceable in code rather than merely encouraged in a prompt. A model that
    notices the lesson is off-topic but still answers "pass" (which happened: a
    Grade 1 quantum entanglement request came back as an approved lesson about
    solids and liquids) is overruled by `topic_drift_forces_fail` below.

    What this does NOT do: it cannot independently detect drift. It enforces
    what this same model self-reports, so a Reviewer that wrongly believes the
    lesson is on topic still passes it. The guarantee is "a model that spots
    drift cannot then approve it", not "drift is impossible".

    This is internal. It is projected to the spec's exact {status, feedback}
    shape by `to_output()` before it ever reaches the API or the UI.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["pass", "fail"]
    # Required in the provider schema. When it was optional, Gemini frequently
    # returned {status: "fail"} without feedback and exhausted the repair loop.
    feedback: list[str]
    # Required, with no default: a default of True fails OPEN. If the model
    # omitted the field the lesson would be treated as on-topic and could be
    # approved — exactly the failure this field exists to prevent. Required means
    # an omission raises ValidationError and the Reviewer fails closed instead of
    # silently approving content whose topic coverage was not judged.
    addresses_requested_topic: bool

    @field_validator("status", mode="before")
    @classmethod
    def status_is_binary(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"pass", "fail"}:
            raise ValueError("status must be exactly 'pass' or 'fail'")
        return v

    @model_validator(mode="after")
    def topic_drift_forces_fail(self):
        """Off-topic content can never pass, whatever the model said."""
        if not self.addresses_requested_topic:
            self.status = "fail"
            if TOPIC_DRIFT_FEEDBACK not in self.feedback:
                self.feedback = [TOPIC_DRIFT_FEEDBACK, *self.feedback]
        return self

    @model_validator(mode="after")
    def fail_must_explain(self):
        # A "fail" with no feedback is useless — the refinement pass needs something to act on.
        if self.status == "fail" and not [f for f in self.feedback if f.strip()]:
            raise ValueError("a 'fail' verdict must include at least one feedback item")
        return self

    def to_output(self) -> "ReviewerOutput":
        return ReviewerOutput(status=self.status, feedback=self.feedback)


class ReviewerOutput(BaseModel):
    """Spec output: {"status": "pass"|"fail", "feedback": [...]}

    Binary pass/fail is deliberate — it matches the spec and is harder for a
    judge model to game than a numeric score. This is the public shape; the
    Reviewer's richer internal judgement lives in ReviewerJudgement.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["pass", "fail"]
    feedback: list[str] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def status_is_binary(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"pass", "fail"}:
            raise ValueError("status must be exactly 'pass' or 'fail'")
        return v

    @model_validator(mode="after")
    def fail_must_explain(self):
        if self.status == "fail" and not [f for f in self.feedback if f.strip()]:
            raise ValueError("a 'fail' verdict must include at least one feedback item")
        return self
