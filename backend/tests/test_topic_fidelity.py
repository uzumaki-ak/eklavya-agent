"""The pipeline must never approve a lesson about a different subject.

Regression for a live failure: Grade 1 / "quantum entanglement" produced a
lesson about solids, liquids and gases, and the final review returned pass —
so a child saw a green "Checked and approved" tick on an answer to a question
they had not asked.

Two independent guarantees are pinned here:
  1. The Reviewer is *told* the topic (it previously received only grade and
     content, which made its own coverage criterion unevaluable).
  2. An off-topic judgement is forced to fail in code, whatever the model said.
"""

import pytest
from pydantic import ValidationError

from app.agents.prompts import REVIEWER_USER
from app.schemas.content import TOPIC_DRIFT_FEEDBACK, ReviewerJudgement


def test_reviewer_prompt_receives_the_topic():
    """Criterion 4 is unevaluable if the topic never reaches the model."""
    rendered = REVIEWER_USER.format(grade=4, topic="Types of angles", content="{}")
    assert "Types of angles" in rendered


def test_reviewer_agent_signature_requires_topic():
    """Guards against the topic being quietly dropped from the call again."""
    import inspect

    from app.agents.reviewer import ReviewerAgent

    assert "topic" in inspect.signature(ReviewerAgent.run).parameters


def test_off_topic_is_forced_to_fail_even_when_model_says_pass():
    """The model approving off-topic content must not be able to ship it."""
    judgement = ReviewerJudgement(
        status="pass",
        feedback=[],
        addresses_requested_topic=False,
    )
    assert judgement.status == "fail"
    assert TOPIC_DRIFT_FEEDBACK in judgement.feedback


def test_topic_drift_feedback_is_not_duplicated():
    judgement = ReviewerJudgement(
        status="fail",
        feedback=[TOPIC_DRIFT_FEEDBACK],
        addresses_requested_topic=False,
    )
    assert judgement.feedback.count(TOPIC_DRIFT_FEEDBACK) == 1


def test_on_topic_pass_is_left_alone():
    judgement = ReviewerJudgement(status="pass", feedback=[], addresses_requested_topic=True)
    assert judgement.status == "pass"
    assert judgement.feedback == []


def test_judgement_projects_to_the_spec_shape():
    """The internal field must not leak into the assessment's public contract."""
    output = ReviewerJudgement(
        status="pass", feedback=[], addresses_requested_topic=False
    ).to_output()

    assert set(output.model_dump()) == {"status", "feedback"}
    assert output.status == "fail"  # the forced verdict survives the projection


def test_addresses_requested_topic_defaults_to_true():
    """A model that omits the field must not accidentally fail every run."""
    assert ReviewerJudgement(status="pass", feedback=[]).addresses_requested_topic is True


def test_fail_still_requires_feedback():
    with pytest.raises(ValidationError):
        ReviewerJudgement(status="fail", feedback=[], addresses_requested_topic=True)


def test_reviewer_is_told_not_to_replace_the_topic():
    """The Reviewer previously asked for topic substitution, and the Generator obeyed."""
    from app.agents.prompts import GENERATOR_REFINE_USER, REVIEWER_SYSTEM

    assert "never ask for the topic to" in REVIEWER_SYSTEM.lower()
    # And the Generator is told to ignore such a request if one arrives anyway.
    assert "topic stays exactly the same" in GENERATOR_REFINE_USER.lower()
