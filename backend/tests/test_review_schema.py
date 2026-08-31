"""The Reviewer's quantitative contract, and the Tagger's closed sets.

The verdict is derived, never trusted: these pin that a model cannot approve
content its own scores condemn, and that feedback must point somewhere real.
"""

import pytest
from pydantic import ValidationError

from app.agents.contract import check_review_paths_exist
from app.core.exceptions import ContentContractError
from app.schemas.review import (
    PASS_THRESHOLDS,
    ReviewerJudgement,
    ReviewerOutput,
    ReviewFeedback,
)
from app.schemas.tags import ContentTags
from tests.factories import PERFECT_SCORES, generator_output, judgement, tags


# --- Reviewer --------------------------------------------------------------


def test_scores_are_bounded():
    with pytest.raises(ValidationError):
        judgement(scores={**PERFECT_SCORES, "clarity": 6})


def test_feedback_must_name_a_real_field():
    with pytest.raises(ValidationError):
        ReviewFeedback.model_validate({"field": "the explanation", "issue": "too hard"})


def test_feedback_index_must_exist_in_the_reviewed_content():
    verdict = judgement(
        passed=False,
        feedback=[{"field": "mcqs[99].question", "issue": "This is unclear."}],
    )
    with pytest.raises(ContentContractError, match="draft has 1 MCQ"):
        check_review_paths_exist(verdict, generator_output())


@pytest.mark.parametrize(
    "path",
    [
        "explanation.text",
        "explanation.grade",
        "teacher_notes.learning_objective",
        "teacher_notes.common_misconceptions[1]",
        "mcqs[0]",
        "mcqs[2].question",
        "mcqs[0].options",
        "mcqs[0].options[3]",
        "mcqs[1].correct_index",
    ],
)
def test_real_field_paths_are_accepted(path):
    assert ReviewFeedback(field=path, issue="x").field == path


def test_thresholds_are_the_documented_ones():
    """The README quotes these; a silent change here would make it wrong."""
    assert PASS_THRESHOLDS == {
        "correctness": 5,
        "age_appropriateness": 4,
        "clarity": 4,
        "coverage": 4,
    }


def test_a_clean_review_passes():
    assert judgement().passed is True


@pytest.mark.parametrize("dimension", sorted(PASS_THRESHOLDS))
def test_any_dimension_below_threshold_fails(dimension):
    verdict = judgement(scores={**PERFECT_SCORES, dimension: PASS_THRESHOLDS[dimension] - 1})
    assert verdict.passed is False
    assert any(dimension in item.issue for item in verdict.feedback)


def test_correctness_of_four_is_not_good_enough():
    """The one dimension with no tolerance."""
    assert judgement(scores={**PERFECT_SCORES, "correctness": 4}).passed is False


def test_a_model_claiming_pass_with_bad_scores_is_overruled():
    verdict = judgement(passed=True, scores={**PERFECT_SCORES, "correctness": 2}, feedback=[])
    assert verdict.reported_pass is True
    assert verdict.passed is False
    assert verdict.overruled is True


def test_a_model_claiming_pass_with_outstanding_feedback_is_overruled():
    verdict = judgement(
        passed=True,
        feedback=[{"field": "mcqs[0].question", "issue": "Two options are correct."}],
    )
    assert verdict.passed is False


def test_off_topic_cannot_pass_however_high_the_scores():
    verdict = judgement(passed=True, on_topic=False, feedback=[])
    assert verdict.passed is False
    assert "does not teach the topic" in verdict.feedback[0].issue


def test_drift_feedback_is_not_duplicated():
    once = judgement(on_topic=False, feedback=[])
    twice = ReviewerJudgement.model_validate(
        {
            "scores": PERFECT_SCORES,
            "pass": False,
            "feedback": [f.model_dump() for f in once.feedback],
            "addresses_requested_topic": False,
        }
    )
    assert len(twice.feedback) == len(once.feedback)


def test_judgement_projects_to_the_spec_shape():
    output = judgement().to_output()
    dumped = output.model_dump(by_alias=True)
    assert set(dumped) == {"scores", "pass", "feedback"}
    assert dumped["pass"] is True


def test_public_review_rejects_a_fail_with_no_explanation():
    with pytest.raises(ValidationError):
        ReviewerOutput.model_validate({"scores": PERFECT_SCORES, "pass": False, "feedback": []})


def test_public_review_rejects_a_pass_carrying_complaints():
    with pytest.raises(ValidationError):
        ReviewerOutput.model_validate(
            {
                "scores": PERFECT_SCORES,
                "pass": True,
                "feedback": [{"field": "explanation.text", "issue": "too long"}],
            }
        )


def test_omitting_the_topic_flag_fails_closed():
    """A default of True would let an unjudged lesson be approved."""
    with pytest.raises(ValidationError):
        ReviewerJudgement.model_validate(
            {"scores": PERFECT_SCORES, "pass": True, "feedback": []}
        )


def test_provider_schema_requires_every_enforced_field():
    required = ReviewerJudgement.model_json_schema()["required"]
    for name in ("scores", "pass", "feedback", "addresses_requested_topic"):
        assert name in required


# --- Tags ------------------------------------------------------------------


def test_valid_tags_accepted():
    assert tags().subject == "Science"


def test_unknown_subject_rejected():
    with pytest.raises(ValidationError):
        tags(subject="Astrophysics")


def test_unknown_blooms_level_rejected():
    with pytest.raises(ValidationError):
        tags(blooms_level="Memorising")


def test_content_type_must_not_repeat():
    with pytest.raises(ValidationError):
        ContentTags.model_validate(
            {**tags().model_dump(), "content_type": ["Quiz", "Quiz"]}
        )
