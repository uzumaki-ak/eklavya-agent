"""The correct answer must not be predictably first — and must stay correct.

The live generator put the answer at index 0 in six of nine sampled questions and
never below index 1, which makes the quiz answerable without reading it.

Part 2 raised the stakes: the answer is now an index rather than text, so a
permutation that forgets to re-derive it does not merely bias the quiz, it makes
every answer wrong. That is what `test_index_follows_the_answer_text` guards.
"""

import time
from collections import Counter

from app.agents import execution as execution_module
from app.agents.execution import ExecutionContext
from app.agents.generator import GeneratorAgent
from app.agents.option_order import balanced_mcq, balanced_options, balanced_output
from app.schemas.content import MCQ, GeneratorInput, GeneratorOutput
from tests.factories import OPTIONS, draft, mcq


def _question(correct_index: int = 0) -> MCQ:
    return MCQ.model_validate(mcq(correct_index=correct_index))


def test_order_is_stable_across_calls():
    first = balanced_options("Why is the sky blue?", list(OPTIONS))
    second = balanced_options("Why is the sky blue?", list(OPTIONS))
    assert first == second


def test_order_is_idempotent():
    once = balanced_options("Why is the sky blue?", list(OPTIONS))
    twice = balanced_options("Why is the sky blue?", once)
    assert once == twice


def test_the_same_options_come_back():
    reordered = balanced_options("Why is the sky blue?", list(OPTIONS))
    assert sorted(reordered) == sorted(OPTIONS)
    assert len(reordered) == 4


def test_index_follows_the_answer_text():
    """The whole risk of the correct_index migration, in one assertion."""
    for correct_index in range(4):
        original = _question(correct_index)
        expected = original.options[correct_index]
        rebalanced = balanced_mcq(original)
        assert rebalanced.options[rebalanced.correct_index] == expected


def test_rebalancing_is_idempotent():
    once = balanced_mcq(_question(2))
    twice = balanced_mcq(once)
    assert twice.options == once.options
    assert twice.correct_index == once.correct_index


def test_rebalancing_keeps_the_same_options():
    rebalanced = balanced_mcq(_question(1))
    assert sorted(rebalanced.options) == sorted(OPTIONS)


def test_answer_reaches_every_position_and_none_dominates():
    """The real guard: a first-position bias must not survive the reordering."""
    positions = Counter()
    for i in range(200):
        options = [f"correct {i}", f"wrong a {i}", f"wrong b {i}", f"wrong c {i}"]
        question = MCQ(question=f"Question {i}?", options=options, correct_index=0)
        rebalanced = balanced_mcq(question)
        positions[rebalanced.correct_index] += 1

    assert set(positions) == {0, 1, 2, 3}, "some position is never used"
    assert max(positions.values()) < 80, f"one position dominates: {positions}"


def test_whole_output_is_rebalanced_off_index_zero():
    output = GeneratorOutput.model_validate(draft(questions=10, correct_index=0))
    rebalanced = balanced_output(output)
    indexes = {question.correct_index for question in rebalanced.mcqs}
    assert indexes != {0}, "every answer is still first"
    assert all(
        question.answer == "The Sun" for question in rebalanced.mcqs
    ), "rebalancing changed which option is correct"


async def test_generator_rebalances_before_returning(monkeypatch):
    """The agent applies it, so the Reviewer sees the order the child sees."""

    async def fake_call_llm(**_kwargs):
        return GeneratorOutput.model_validate(draft(questions=8, correct_index=0))

    monkeypatch.setattr(execution_module, "call_llm", fake_call_llm)
    result = await GeneratorAgent().run(
        GeneratorInput(grade=5, topic="The solar system"),
        ExecutionContext(deadline=time.monotonic() + 10),
    )

    assert {question.correct_index for question in result.mcqs} != {0}
    assert all(question.answer == "The Sun" for question in result.mcqs)
