"""Schema contract tests.

These guard the assessment's "deterministic structure" requirement — especially
the cross-field rules the API's own schema enforcement cannot express.
"""

import pytest
from pydantic import ValidationError

from app.schemas.content import MCQ, GeneratorOutput, ReviewerOutput

VALID_MCQ = {
    "question": "Which angle is exactly 90 degrees?",
    "options": ["Acute", "Right", "Obtuse", "Straight"],
    "answer": "Right",
}


def test_valid_mcq_accepted():
    mcq = MCQ(**VALID_MCQ)
    assert mcq.answer == "Right"
    assert len(mcq.options) == 4


def test_answer_must_be_one_of_the_options():
    with pytest.raises(ValidationError, match="answer must exactly match"):
        MCQ(**{**VALID_MCQ, "answer": "Reflex"})


def test_duplicate_options_rejected():
    with pytest.raises(ValidationError, match="four distinct"):
        MCQ(**{**VALID_MCQ, "options": ["Right", "Right", "Obtuse", "Acute"]})


def test_blank_option_rejected():
    with pytest.raises(ValidationError, match="must not be blank"):
        MCQ(**{**VALID_MCQ, "options": ["Acute", "Right", "   ", "Straight"]})


def test_blank_question_rejected():
    with pytest.raises(ValidationError):
        MCQ(**{**VALID_MCQ, "question": "   "})


def test_extra_fields_rejected():
    # "Deterministic structure" means exactly this shape — no bonus keys.
    with pytest.raises(ValidationError):
        MCQ(**{**VALID_MCQ, "difficulty": "easy"})


def test_wrong_option_count_rejected():
    with pytest.raises(ValidationError):
        MCQ(**{**VALID_MCQ, "options": ["Acute", "Right", "Obtuse"]})


def test_generator_output_requires_mcqs():
    with pytest.raises(ValidationError):
        GeneratorOutput(explanation="Angles are corners.", mcqs=[])


def test_reviewer_status_must_be_binary():
    with pytest.raises(ValidationError, match="exactly 'pass' or 'fail'"):
        ReviewerOutput(status="maybe", feedback=[])


def test_reviewer_status_is_normalized():
    assert ReviewerOutput(status="PASS", feedback=[]).status == "pass"


def test_fail_without_feedback_rejected():
    # A failing verdict with no reasons gives the refinement pass nothing to act on.
    with pytest.raises(ValidationError, match="must include at least one feedback"):
        ReviewerOutput(status="fail", feedback=[])


def test_fail_with_feedback_accepted():
    review = ReviewerOutput(status="fail", feedback=["Sentence 2 is too complex for Grade 4"])
    assert review.status == "fail"
