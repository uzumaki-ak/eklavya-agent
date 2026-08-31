"""The Generator's strict schema — the contract the provider cannot enforce for us.

The Reviewer and Tagger schemas are in `test_review_schema.py`.
"""

import pytest
from pydantic import ValidationError

from app.schemas.content import MCQ, GeneratorOutput, TeacherNotes
from tests.factories import draft, mcq


# --- Generator content -----------------------------------------------------


def test_valid_draft_accepted():
    output = GeneratorOutput.model_validate(draft())
    assert output.explanation.grade == 5
    assert output.mcqs[0].answer == "The Sun"


def test_correct_index_must_be_in_range():
    with pytest.raises(ValidationError):
        MCQ.model_validate(mcq(correct_index=4))


def test_correct_index_must_not_be_negative():
    with pytest.raises(ValidationError):
        MCQ.model_validate(mcq(correct_index=-1))


def test_answer_property_follows_the_index():
    question = MCQ.model_validate(mcq(correct_index=2))
    assert question.answer == question.options[2]


def test_duplicate_options_rejected():
    with pytest.raises(ValidationError):
        MCQ.model_validate(mcq(options=["A", "A", "B", "C"]))


def test_blank_option_rejected():
    with pytest.raises(ValidationError):
        MCQ.model_validate(mcq(options=["A", "   ", "B", "C"]))


@pytest.mark.parametrize(
    "position_dependent_option",
    [
        "All of the above",
        "None of the above",
        "Both A and B",
        "Option A or Option C",
        "The first option",
        "A. An acute angle",
        "B) Mercury",
    ],
)
def test_position_dependent_options_rejected(position_dependent_option):
    """The options are reordered, so anything naming a position stops being true."""
    with pytest.raises(ValidationError):
        MCQ.model_validate(
            mcq(options=[position_dependent_option, "Mercury", "Venus", "Mars"])
        )


def test_semantic_both_wording_is_not_mistaken_for_option_labels():
    question = MCQ.model_validate(
        mcq(
            options=[
                "Both evaporation and condensation",
                "Only evaporation",
                "Only condensation",
                "Neither process",
            ]
        )
    )
    assert question.options[0] == "Both evaporation and condensation"


def test_explanation_must_carry_a_grade():
    payload = draft()
    del payload["explanation"]["grade"]
    with pytest.raises(ValidationError):
        GeneratorOutput.model_validate(payload)


def test_teacher_notes_are_required():
    payload = draft()
    del payload["teacher_notes"]
    with pytest.raises(ValidationError):
        GeneratorOutput.model_validate(payload)


def test_teacher_notes_reject_blank_misconceptions():
    with pytest.raises(ValidationError):
        TeacherNotes.model_validate(
            {"learning_objective": "Do a thing", "common_misconceptions": ["  "]}
        )


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        GeneratorOutput.model_validate({**draft(), "unexpected": 1})


def test_moderation_blob_covers_every_model_written_field():
    """teacher_notes must not be a channel that bypasses the safety filter."""
    output = GeneratorOutput.model_validate(draft())
    blob = output.moderation_blob()
    assert output.explanation.text in blob
    assert output.teacher_notes.learning_objective in blob
    for misconception in output.teacher_notes.common_misconceptions:
        assert misconception in blob
    for question in output.mcqs:
        assert question.question in blob
        for option in question.options:
            assert option in blob
