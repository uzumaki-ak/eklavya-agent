"""Content rules that need context outside the payload being validated.

Pydantic can only check a payload against itself. "The explanation must be
written for the grade that was asked for" compares the payload to the request,
which the schema never sees — so it is enforced here, at the one layer that
holds both.

These raise `ContentContractError`, which the agents' bounded repair loops treat
exactly like a schema failure: the message goes back to the model and it gets its
one retry.
"""

import re

from app.core.exceptions import ContentContractError
from app.schemas.content import GeneratorInput, GeneratorOutput
from app.schemas.review import ReviewerJudgement
from app.schemas.tags import ContentTags

_MCQ_PATH_RE = re.compile(r"^mcqs\[(\d+)\](?:\.options\[(\d+)\])?")
_MISCONCEPTION_PATH_RE = re.compile(
    r"^teacher_notes\.common_misconceptions\[(\d+)\]$"
)


def check_generated_matches_request(output: GeneratorOutput, data: GeneratorInput) -> None:
    """The declared grade must be the grade that was requested.

    A mismatch is not cosmetic: `explanation.grade` is what a downstream consumer
    reads to decide who the lesson is for, so a Grade 9 explanation labelled
    Grade 2 is worse than an unlabelled one.
    """
    if output.explanation.grade != data.grade:
        raise ContentContractError(
            f"explanation.grade is {output.explanation.grade} but the requested "
            f"grade is {data.grade}. Set explanation.grade to {data.grade} and "
            f"write the lesson at that reading level."
        )


def check_tags_match_request(tags: ContentTags, data: GeneratorInput) -> None:
    """The Tagger classifies what was produced; it does not get to reassign the grade."""
    if tags.grade != data.grade:
        raise ContentContractError(
            f"grade is {tags.grade} but the content was generated for grade "
            f"{data.grade}. Set grade to {data.grade}."
        )


def check_review_paths_exist(
    judgement: ReviewerJudgement,
    content: GeneratorOutput,
) -> None:
    """Reject syntactically valid feedback paths that point outside the draft."""
    for feedback in judgement.feedback:
        mcq_match = _MCQ_PATH_RE.match(feedback.field)
        if mcq_match:
            mcq_index = int(mcq_match.group(1))
            if mcq_index >= len(content.mcqs):
                raise ContentContractError(
                    f"feedback field {feedback.field!r} references MCQ {mcq_index}, "
                    f"but the draft has {len(content.mcqs)} MCQ(s)"
                )
            option_index = mcq_match.group(2)
            if option_index is not None and int(option_index) >= len(
                content.mcqs[mcq_index].options
            ):
                raise ContentContractError(
                    f"feedback field {feedback.field!r} references an option "
                    "that does not exist"
                )

        misconception_match = _MISCONCEPTION_PATH_RE.match(feedback.field)
        if misconception_match and int(misconception_match.group(1)) >= len(
            content.teacher_notes.common_misconceptions
        ):
            raise ContentContractError(
                f"feedback field {feedback.field!r} references a misconception "
                "that does not exist"
            )
