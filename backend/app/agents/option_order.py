"""Deterministic MCQ option ordering.

The model writes the correct answer first and then pads with distractors, so
generated quizzes were answerable by always tapping the top box: across a live
sample of nine questions the answer sat at index 0 six times and index 1 three
times, never lower. Asking a model to randomise the position in the prompt is
advisory and unreliable, so the order is fixed in code instead.

The permutation is a pure function of the question and its option set. That keeps
it stable across regenerations and cache reuse, and idempotent - sorting before
shuffling means re-applying it cannot move anything a second time.

Part 2 made this sharper. The answer used to be stored as text, so a permutation
was automatically safe. It is now an index, which a permutation invalidates, so
`balanced_mcq` re-derives the index from the answer's *text* after reordering.
Never carry a pre-shuffle index across.
"""

import hashlib
import random

from app.schemas.content import MCQ, GeneratorOutput

_SEED_BYTES = 8


def _seed(question: str, ordered: list[str]) -> int:
    material = "|".join([question, *ordered]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:_SEED_BYTES], "big")


def balanced_options(question: str, options: list[str]) -> list[str]:
    """Same options, in a stable order that does not favour any position."""
    ordered = sorted(options)
    random.Random(_seed(question, ordered)).shuffle(ordered)
    return ordered


def balanced_mcq(mcq: MCQ) -> MCQ:
    """Reorder one question's options and re-derive `correct_index`.

    Returns a new, re-validated MCQ rather than mutating in place, so the
    post-shuffle object has been through the same checks as the original.
    Options are guaranteed distinct by the schema, so locating the answer text
    in the reordered list is unambiguous.
    """
    answer = mcq.options[mcq.correct_index]
    ordered = balanced_options(mcq.question, mcq.options)
    return MCQ(
        question=mcq.question,
        options=ordered,
        correct_index=ordered.index(answer),
    )


def balanced_output(output: GeneratorOutput) -> GeneratorOutput:
    """Rebalance every question in a draft.

    Applied after validation, by both the Generator and the Refiner, so the
    Reviewer always judges the option order the child will actually see.
    """
    output.mcqs = [balanced_mcq(mcq) for mcq in output.mcqs]
    return output
