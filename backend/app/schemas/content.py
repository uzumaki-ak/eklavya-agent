"""Generator I/O schemas — the Part 2 strict contract.

Shape is enforced by each provider's native structured output; the cross-field
rules below (distinct options, position-independent options) are Python-level
and raise ValidationError, which is why the Generator needs its own bounded
schema-repair pass.

One rule deliberately does NOT live here: `explanation.grade` must equal the
*requested* grade, which this model has no way of knowing. That check belongs to
the agent, which does know it — see `app.agents.contract.check_matches_request`.
"""

import re

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

OPTION_COUNT = 4


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


def _stripped_or_fail(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class Explanation(BaseModel):
    """The taught content, tagged with the grade it was written for.

    Carrying the grade inside the payload is what lets a downstream consumer —
    or the audit trail — see which reading level a stored lesson was written to,
    without needing the original request beside it.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    grade: int = Field(ge=1, le=12)

    _clean_text = field_validator("text")(_stripped_or_fail)


class MCQ(BaseModel):
    """One question. The answer is an index, not text.

    Part 1 stored the answer as a string, which made the deterministic option
    shuffle trivially safe. An index does not survive a permutation on its own,
    so `app.agents.option_order.balanced_mcq` re-derives it — never reuse a
    pre-shuffle index.
    """

    model_config = ConfigDict(extra="forbid")

    question: str
    # A bounded list maps to the portable JSON Schema minItems/maxItems shape.
    # A fixed Python tuple emits prefixItems, which Gemini Generate Content's
    # current SDK schema converter rejects before making the API call.
    options: list[str] = Field(min_length=OPTION_COUNT, max_length=OPTION_COUNT)
    correct_index: int = Field(ge=0, le=OPTION_COUNT - 1)

    _clean_question = field_validator("question")(_stripped_or_fail)

    @model_validator(mode="after")
    def check_options(self):
        normalized = [o.strip() for o in self.options]
        if any(not o for o in normalized):
            raise ValueError("options must not be blank")
        if any(_depends_on_option_position(o) for o in normalized):
            raise ValueError(
                "options must not depend on positions or labels such as "
                "'all of the above', 'both A and B', or 'the first option'"
            )
        if len(set(normalized)) != OPTION_COUNT:
            raise ValueError(f"options must be {OPTION_COUNT} distinct strings")
        return self

    @property
    def answer(self) -> str:
        """The correct option's text. Bounds are guaranteed by the field rules."""
        return self.options[self.correct_index]


class TeacherNotes(BaseModel):
    """Guidance for the adult, never shown to the child."""

    model_config = ConfigDict(extra="forbid")

    learning_objective: str
    common_misconceptions: list[str] = Field(min_length=1, max_length=5)

    _clean_objective = field_validator("learning_objective")(_stripped_or_fail)

    @field_validator("common_misconceptions")
    @classmethod
    def misconceptions_not_blank(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values]
        if any(not v for v in cleaned):
            raise ValueError("common_misconceptions must not contain blank entries")
        return cleaned


class GeneratorInput(BaseModel):
    """Spec input: {"grade": 5, "topic": "Fractions as parts of a whole"}"""

    model_config = ConfigDict(extra="forbid")

    grade: int = Field(ge=1, le=12)
    topic: str = Field(min_length=1, max_length=200)


class GeneratorOutput(BaseModel):
    """Spec output: explanation + mcqs + teacher_notes."""

    model_config = ConfigDict(extra="forbid")

    explanation: Explanation
    mcqs: list[MCQ] = Field(min_length=1, max_length=10)
    teacher_notes: TeacherNotes

    def moderation_blob(self) -> str:
        """Every free-text field a model wrote, for the safety pre-filter.

        Built here rather than in the moderation service so that adding a field
        to this schema and forgetting to screen it is a change to one file, not
        a silent gap between two. `teacher_notes` was exactly that gap when the
        Part 2 schema landed.
        """
        parts = [self.explanation.text, self.teacher_notes.learning_objective]
        parts.extend(self.teacher_notes.common_misconceptions)
        for mcq in self.mcqs:
            parts.append(mcq.question)
            parts.extend(mcq.options)
        return " ".join(parts)
