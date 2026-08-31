"""Builders for the Part 2 schemas.

Tests state the one thing they are about and take defaults for the rest, so a
schema change lands here once instead of in every test file.
"""

from app.schemas.content import GeneratorOutput
from app.schemas.review import ReviewerJudgement, ReviewerOutput
from app.schemas.tags import ContentTags

PERFECT_SCORES = {
    "age_appropriateness": 5,
    "correctness": 5,
    "clarity": 5,
    "coverage": 5,
}

OPTIONS = ["The Sun", "The Moon", "Planet Earth", "A giant cloud"]


def mcq(index: int = 0, *, correct_index: int = 0, options: list[str] | None = None) -> dict:
    return {
        "question": f"What is at the centre of the solar system? ({index})",
        "options": list(options or OPTIONS),
        "correct_index": correct_index,
    }


def draft(
    *,
    grade: int = 5,
    text: str = "The Sun sits at the centre of the solar system.",
    questions: int = 1,
    correct_index: int = 0,
) -> dict:
    """A valid GeneratorOutput payload."""
    return {
        "explanation": {"text": text, "grade": grade},
        "mcqs": [mcq(i, correct_index=correct_index) for i in range(questions)],
        "teacher_notes": {
            "learning_objective": "Name the star at the centre of the solar system.",
            "common_misconceptions": ["The Earth is at the centre."],
        },
    }


def generator_output(**kwargs) -> GeneratorOutput:
    return GeneratorOutput.model_validate(draft(**kwargs))


def judgement(
    *,
    passed: bool = True,
    on_topic: bool = True,
    scores: dict | None = None,
    feedback: list[dict] | None = None,
) -> ReviewerJudgement:
    """A ReviewerJudgement as the model would answer it.

    Defaults to a clean pass. Asking for `passed=False` without explicit scores
    lowers correctness, which is what a real failing review looks like — the
    verdict follows from the scores rather than being asserted alongside them.
    """
    if scores is None:
        scores = dict(PERFECT_SCORES)
        if not passed:
            scores["correctness"] = 3
    if feedback is None:
        feedback = (
            []
            if passed
            else [{"field": "mcqs[0].question", "issue": "Two options are correct."}]
        )
    return ReviewerJudgement.model_validate(
        {
            "scores": scores,
            "pass": passed,
            "feedback": feedback,
            "addresses_requested_topic": on_topic,
        }
    )


def review(**kwargs) -> ReviewerOutput:
    return judgement(**kwargs).to_output()


def review_dict(**kwargs) -> dict:
    """Stored form — `by_alias`, so the key is the spec's "pass"."""
    return review(**kwargs).model_dump(by_alias=True)


def tags(**overrides) -> ContentTags:
    payload = {
        "subject": "Science",
        "topic": "The Solar System",
        "grade": 5,
        "difficulty": "Medium",
        "content_type": ["Explanation", "Quiz"],
        "blooms_level": "Understanding",
    }
    payload.update(overrides)
    return ContentTags.model_validate(payload)
