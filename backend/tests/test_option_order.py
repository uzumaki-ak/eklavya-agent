"""The correct answer must not be predictably first.

The live generator put the answer at index 0 in six of nine sampled questions
and never below index 1, which makes the quiz answerable without reading it.
"""

import time
from collections import Counter

from app.agents import generator as generator_module
from app.agents.generator import ExecutionContext, GeneratorAgent, _spread_answer_positions
from app.agents.option_order import balanced_options
from app.schemas.content import GeneratorInput, GeneratorOutput

_OPTIONS = ["The Sun", "The Moon", "Planet Earth", "A giant cloud"]


def _output(count: int = 1) -> GeneratorOutput:
    """`count` questions, each with the correct answer deliberately placed first."""
    return GeneratorOutput.model_validate(
        {
            "explanation": "The Sun sits at the centre of the solar system.",
            "mcqs": [
                {
                    "question": f"What is at the centre of the solar system? ({i})",
                    "options": list(_OPTIONS),
                    "answer": _OPTIONS[0],
                }
                for i in range(count)
            ],
        }
    )


def test_order_is_stable_across_calls():
    first = balanced_options("Why is the sky blue?", list(_OPTIONS))
    second = balanced_options("Why is the sky blue?", list(_OPTIONS))
    assert first == second


def test_order_is_idempotent():
    once = balanced_options("Why is the sky blue?", list(_OPTIONS))
    twice = balanced_options("Why is the sky blue?", once)
    assert once == twice


def test_the_same_options_come_back():
    reordered = balanced_options("Why is the sky blue?", list(_OPTIONS))
    assert sorted(reordered) == sorted(_OPTIONS)
    assert len(reordered) == 4


def test_answer_reaches_every_position_and_none_dominates():
    """The real guard: a first-position bias must not survive the reordering."""
    positions = Counter()
    for i in range(200):
        options = [f"correct {i}", f"wrong a {i}", f"wrong b {i}", f"wrong c {i}"]
        reordered = balanced_options(f"Question {i}?", options)
        positions[reordered.index(options[0])] += 1

    assert set(positions) == {0, 1, 2, 3}, "some position is never used"
    assert max(positions.values()) < 80, f"one position dominates: {positions}"


def test_spread_preserves_the_answer():
    output = _spread_answer_positions(_output())
    mcq = output.mcqs[0]
    assert mcq.answer in mcq.options
    assert sorted(mcq.options) == sorted(_OPTIONS)


def test_spread_moves_an_answer_first_quiz_off_index_zero():
    output = _spread_answer_positions(_output(count=10))
    indexes = {mcq.options.index(mcq.answer) for mcq in output.mcqs}
    assert indexes != {0}, "every answer is still first"


async def test_generator_reorders_before_returning(monkeypatch):
    """The agent applies it, so the Reviewer sees the order the child sees."""

    async def fake_call_llm(**_kwargs):
        return _output(count=8)

    monkeypatch.setattr(generator_module, "call_llm", fake_call_llm)
    result = await GeneratorAgent().run(
        GeneratorInput(grade=5, topic="The solar system"),
        ExecutionContext(deadline=time.monotonic() + 10),
    )

    indexes = {mcq.options.index(mcq.answer) for mcq in result.mcqs}
    assert indexes != {0}
    assert all(mcq.answer in mcq.options for mcq in result.mcqs)
